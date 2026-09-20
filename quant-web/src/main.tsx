import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

// Vite 的 base (如 '/qg/') 不会自动作用于 React Router，
// 必须显式传给 BrowserRouter.basename，否则 <Link to="/x"> 会生成 /x 而不是 /qg/x。
// 去掉尾部斜杠：React Router v6 的 basename 约定不带尾斜杠。
const basename = import.meta.env.BASE_URL.replace(/\/+$/, '') || '/';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);