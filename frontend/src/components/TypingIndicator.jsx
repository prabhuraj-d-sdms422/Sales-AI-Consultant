export default function TypingIndicator() {
  return (
    <div className="flex gap-1.5 items-center text-slate-400 text-xs">
      <span className="typing-dot" style={{ animationDelay: "0ms" }}>
        •
      </span>
      <span className="typing-dot" style={{ animationDelay: "120ms" }}>
        •
      </span>
      <span className="typing-dot" style={{ animationDelay: "240ms" }}>
        •
      </span>
    </div>
  );
}
