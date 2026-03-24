export default function MessageBubble({ role, children }) {
  const isUser = role === "user";
  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"} mb-2`}>
      <div
        className={`max-w-[78%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words border ${
          isUser
            ? "bg-blue-600/20 text-blue-50 border-blue-500/30"
            : "bg-white/[0.03] text-slate-100 border-white/10"
        }`}
      >
        {children}
      </div>
    </div>
  );
}
