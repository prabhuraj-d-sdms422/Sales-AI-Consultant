import ChatWidget from "./components/ChatWidget.jsx";

export default function App() {
  return (
    <div className="h-full bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-slate-100 flex flex-col items-center">
      <div className="w-full max-w-4xl flex-1 px-4 sm:px-6 py-6">
        <div className="mb-4">
          <p className="text-left text-slate-500 text-xs">
            Demo UI — streams responses token by token via SSE
          </p>
        </div>
        <ChatWidget />
      </div>
    </div>
  );
}
