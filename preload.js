const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('friday', {
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close:    () => ipcRenderer.send('window-close'),
  quit:     () => ipcRenderer.send('window-quit'),
})
