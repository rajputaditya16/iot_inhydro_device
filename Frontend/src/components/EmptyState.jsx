import { motion } from 'framer-motion';
import { Inbox } from 'lucide-react';

const EmptyState = ({ icon: Icon = Inbox, title = 'No data found', description = 'There are no items to display at this time.', action }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700/50 bg-slate-800/20 px-6 py-16"
    >
      <div className="rounded-2xl bg-slate-800/50 p-4">
        <Icon className="h-10 w-10 text-slate-600" />
      </div>
      <h3 className="mt-4 text-base font-semibold text-slate-300">{title}</h3>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </motion.div>
  );
};

export default EmptyState;
