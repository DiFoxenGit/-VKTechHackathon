import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource/play/400.css';
import '@fontsource/play/700.css';
import App from './App';
import ServerStudio from './ServerStudio';
import './styles.css';
import './simplified.css';
import './studio.css';

/**
 * Два режима на одной сборке: демо без сервера (по умолчанию) и серверная студия
 * по адресу /#studio, где вся вёрстка приходит с бэкенда вместе с аудитом.
 */
function Root() {
  const [hash, setHash] = React.useState(window.location.hash);
  React.useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return hash.startsWith('#studio') ? <ServerStudio /> : <App />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Root /></React.StrictMode>,
);
