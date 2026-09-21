import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";

// Easter egg  morse code
console.log(
  '%c.--. .- .-. - ....   -.- --- -- .- .-.. .-- .- ..',
  'color: #6366F1; font-family: monospace; font-size: 11px; opacity: 0.6;'
);
console.log(
  '%cIf you found this, you know what it means.',
  'color: #64748B; font-family: monospace; font-size: 10px;'
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
