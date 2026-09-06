import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'
import { installChunkReloadHandler } from './chunkReload.js'
import './styles.css'

// Before render: a chunk can fail to load on the very first lazy view a reader opens, and the
// listener has to already be attached when it does.
installChunkReloadHandler()

createRoot(document.getElementById('root')).render(
  <ErrorBoundary><App /></ErrorBoundary>,
)
