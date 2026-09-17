import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource/play/400.css';
import '@fontsource/play/700.css';
import Studio from './Studio';
import './brand/tokens.css';
import './app.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Studio />
  </React.StrictMode>,
);
