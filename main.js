const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, session } = require('electron')
const path  = require('path')
const { spawn } = require('child_process')
const http  = require('http')

// Fix GPU cache permission errors on Windows
app.commandLine.appendSwitch('disable-gpu')
app.commandLine.appendSwitch('disable-software-rasterizer')

let mainWindow = null
let tray       = null
let pyServer   = null
const PORT     = 5000

// ── Launch Python backend ─────────────────────────────────────────────────────
function startPythonServer() {
  const serverPath = path.join(__dirname, 'server.py')

  // Try 'python' then 'python3'
  const cmd = process.platform === 'win32' ? 'python' : 'python3'
  pyServer = spawn(cmd, [serverPath], {
    cwd: __dirname,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  pyServer.stdout.on('data', d => console.log('[FRIDAY]', d.toString().trim()))
  pyServer.stderr.on('data', d => console.error('[FRIDAY ERR]', d.toString().trim()))

  pyServer.on('error', err => {
    console.error('Failed to start Python server:', err)
  })

  pyServer.on('close', code => {
    console.log(`Python server exited with code ${code}`)
  })
}

// ── Wait for server to be ready ───────────────────────────────────────────────
function waitForServer(retries = 40, delay = 750) {
  return new Promise((resolve, reject) => {
    const attempt = () => {
      http.get(`http://127.0.0.1:${PORT}/`, res => {
        resolve()
      }).on('error', () => {
        if (retries-- > 0) {
          setTimeout(attempt, delay)
        } else {
          reject(new Error('Server did not start in time'))
        }
      })
    }
    attempt()
  })
}

// ── Create main window ────────────────────────────────────────────────────────
async function createWindow() {
  // Only start Python server if not already running
  try {
    await new Promise((resolve, reject) => {
      http.get(`http://127.0.0.1:${PORT}/`, res => resolve()).on('error', () => reject())
    })
    console.log('[FRIDAY] Server already running, skipping Python start')
  } catch {
    startPythonServer()
  }

  mainWindow = new BrowserWindow({
    width:  1400,
    height: 860,
    minWidth:  1000,
    minHeight: 650,
    frame: false,
    transparent: false,
    backgroundColor: '#0a0301',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: false,
      allowRunningInsecureContent: true,
    },
    show: false,
  })

  try {
    await waitForServer()
    console.log('[FRIDAY] Server ready, loading UI')
  } catch (e) {
    console.error('[FRIDAY] Server timeout — loading anyway')
  }

  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`)

  mainWindow.webContents.on('did-fail-load', (event, code, desc) => {
    console.error('[FRIDAY] Page load failed:', code, desc)
    // Retry after 2 seconds
    setTimeout(() => mainWindow && mainWindow.loadURL(`http://127.0.0.1:${PORT}/`), 2000)
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    mainWindow.focus()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ── System Tray ───────────────────────────────────────────────────────────────
function createTray() {
  // Simple 16x16 fallback icon if no asset
  const iconPath = path.join(__dirname, 'assets', 'tray.png')
  let trayIcon
  try {
    trayIcon = nativeImage.createFromPath(iconPath)
  } catch {
    trayIcon = nativeImage.createEmpty()
  }

  tray = new Tray(trayIcon)
  tray.setToolTip('F.R.I.D.A.Y.')

  const menu = Menu.buildFromTemplate([
    { label: 'Show FRIDAY',  click: () => { if (mainWindow) mainWindow.show() } },
    { label: 'Hide',         click: () => { if (mainWindow) mainWindow.hide() } },
    { type: 'separator' },
    { label: 'Quit FRIDAY',  click: () => app.quit() },
  ])
  tray.setContextMenu(menu)

  tray.on('double-click', () => {
    if (mainWindow) mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show()
  })
}

// ── IPC — window controls (called from renderer via preload) ──────────────────
ipcMain.on('window-minimize', () => mainWindow && mainWindow.minimize())
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return
  mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize()
})
ipcMain.on('window-close',    () => mainWindow && mainWindow.hide())   // hide to tray, not quit
ipcMain.on('window-quit',     () => app.quit())

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray()
  await createWindow()
})

app.on('window-all-closed', e => {
  e.preventDefault()    // keep alive in tray
})

app.on('before-quit', () => {
  if (pyServer) pyServer.kill()
})

app.on('activate', () => {
  if (!mainWindow) createWindow()
})
