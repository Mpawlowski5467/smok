#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    time::Duration,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, WebviewUrl, WebviewWindowBuilder,
};

type Server = Arc<Mutex<Option<Child>>>;

fn stop(server: &Server) {
    if let Some(mut child) = server.lock().unwrap().take() {
        #[cfg(unix)]
        unsafe {
            libc::kill(child.id() as i32, libc::SIGTERM);
        }
        for _ in 0..50 {
            if child.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    let server: Server = Arc::new(Mutex::new(None));
    let setup_server = server.clone();
    let result = tauri::Builder::default()
        .setup(move |app| {
            let args: Vec<String> = std::env::args().collect();
            let workspace = args
                .iter()
                .position(|a| a == "--workspace")
                .and_then(|i| args.get(i + 1))
                .map(std::path::PathBuf::from)
                .or_else(|| {
                    rfd::FileDialog::new()
                        .set_title("Choose a workspace for Smok")
                        .pick_folder()
                });
            let Some(workspace) = workspace else {
                app.handle().exit(0);
                return Ok(());
            };
            let executable = std::env::current_exe()?
                .parent()
                .ok_or("Missing executable directory")?
                .join("smok-server");
            let executable = if executable.is_file() {
                executable
            } else {
                // Development uses the same sidecar with Tauri's target-triple suffix.
                let triple = env!("TAURI_ENV_TARGET_TRIPLE");
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join(format!("binaries/smok-server-{triple}"))
            };
            // Finder does not load shell startup files. Keep inherited paths and add
            // standard Homebrew locations for Git, ripgrep, and configured MCP servers.
            let inherited = std::env::var_os("PATH").unwrap_or_default();
            let mut paths: Vec<_> = std::env::split_paths(&inherited).collect();
            for directory in ["/opt/homebrew/bin", "/usr/local/bin"] {
                let path = std::path::PathBuf::from(directory);
                if path.is_dir() && !paths.contains(&path) {
                    paths.push(path);
                }
            }
            let mut child = Command::new(executable)
                .args(["--native", "--port", "0", "--workspace"])
                .arg(&workspace)
                .arg("--parent-pid")
                .arg(std::process::id().to_string())
                .env("PATH", std::env::join_paths(paths)?)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::inherit())
                .spawn()?;
            let stdout = child.stdout.take().ok_or("Server did not provide stdout")?;
            *setup_server.lock().unwrap() = Some(child);
            let (sender, receiver) = std::sync::mpsc::channel();
            std::thread::spawn(move || {
                let mut line = String::new();
                let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
                let _ = sender.send(result);
            });
            let line = receiver.recv_timeout(Duration::from_secs(30))??;
            let data: serde_json::Value = serde_json::from_str(&line)?;
            let url: tauri::Url = data["url"]
                .as_str()
                .ok_or("Invalid server handshake")?
                .parse()?;
            if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") {
                return Err("Server must run on loopback".into());
            }
            let origin = url.origin();
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title(format!(
                    "Smok · {}",
                    workspace.file_name().unwrap_or_default().to_string_lossy()
                ))
                .inner_size(1440.0, 960.0)
                .min_inner_size(800.0, 600.0)
                .on_navigation(move |target| target.origin() == origin)
                .build()?;
            let handle = window.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = handle.hide();
                }
            });
            let show = MenuItem::with_id(app, "show", "Show Smok", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Smok", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().ok_or("Missing app icon")?.clone())
                .tooltip("Smok · Local coding companion")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!());
    match result {
        Ok(app) => {
            let on_exit = server.clone();
            app.run(move |_handle, event| {
                if matches!(event, tauri::RunEvent::Exit) {
                    stop(&on_exit);
                }
            });
        }
        Err(error) => {
            stop(&server);
            rfd::MessageDialog::new()
                .set_title("Smok could not start")
                .set_description(error.to_string())
                .set_level(rfd::MessageLevel::Error)
                .show();
        }
    }
    stop(&server);
}
