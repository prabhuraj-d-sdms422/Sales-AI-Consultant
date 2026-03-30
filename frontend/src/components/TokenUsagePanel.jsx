export default function TokenUsagePanel({ tokenUsage }) {
  const session = tokenUsage?.session;
  const provider = tokenUsage?.provider;
  const model = tokenUsage?.model;

  const tokens = session?.total_tokens;
  const costInr = session?.estimated_cost_inr;

  const hasData = typeof tokens === "number" && typeof costInr === "number";

  return (
    <div className="px-4 py-2 border-b border-white/10 bg-white/[0.02]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-300">
        <span className="font-semibold text-slate-200">Session usage</span>
        <span className="text-slate-500">•</span>
        <span>
          Tokens:{" "}
          <span className="font-medium text-slate-100">
            {hasData ? tokens.toLocaleString() : "—"}
          </span>
        </span>
        <span className="text-slate-500">•</span>
        <span>
          Est. cost:{" "}
          <span className="font-medium text-slate-100">
            {hasData ? `₹${costInr.toFixed(2)}` : "—"}
          </span>
        </span>
        {(provider || model) && (
          <>
            <span className="text-slate-500">•</span>
            <span className="text-slate-400">
              {provider || "provider"} / {model || "model"}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

