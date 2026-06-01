const SkeletonCard = () => (
  <div className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-5">
    <div className="flex items-start justify-between">
      <div className="space-y-3">
        <div className="skeleton h-3 w-24 rounded" />
        <div className="skeleton h-8 w-16 rounded" />
      </div>
      <div className="skeleton h-12 w-12 rounded-xl" />
    </div>
  </div>
);

const SkeletonDeviceCard = () => (
  <div className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-5">
    <div className="mb-4 flex items-start justify-between">
      <div className="space-y-2">
        <div className="skeleton h-4 w-32 rounded" />
        <div className="skeleton h-3 w-24 rounded" />
      </div>
      <div className="skeleton h-6 w-16 rounded-full" />
    </div>
    <div className="grid grid-cols-2 gap-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="skeleton h-5 w-20 rounded" />
      ))}
    </div>
    <div className="mt-4 border-t border-slate-700/30 pt-3">
      <div className="skeleton h-3 w-full rounded" />
    </div>
  </div>
);

const SkeletonTable = ({ rows = 5, cols = 5 }) => (
  <div className="space-y-3">
    <div className="flex gap-4 p-3">
      {[...Array(cols)].map((_, i) => (
        <div key={i} className="skeleton h-4 flex-1 rounded" />
      ))}
    </div>
    {[...Array(rows)].map((_, r) => (
      <div key={r} className="flex gap-4 p-3">
        {[...Array(cols)].map((_, c) => (
          <div key={c} className="skeleton h-4 flex-1 rounded" />
        ))}
      </div>
    ))}
  </div>
);

export { SkeletonCard, SkeletonDeviceCard, SkeletonTable };
