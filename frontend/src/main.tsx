import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#0c6b64",
          colorInfo: "#0c6b64",
          colorSuccess: "#1d8b5f",
          colorWarning: "#c18a21",
          colorError: "#c44b38",
          borderRadius: 20,
          colorBgLayout: "#f8f3e8",
          colorText: "#1d2430",
          colorTextSecondary: "#556173",
          fontFamily: '"IBM Plex Sans", "PingFang SC", "Segoe UI", sans-serif',
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
