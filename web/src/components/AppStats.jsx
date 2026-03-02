import { useState } from 'react';
import { useSystemStats } from '../hooks/useSystemStats';

function formatUptime(seconds) {
  if (!seconds) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function StatCard({ label, value, unit }) {
  return (
    <div className="bg-gray-800 rounded px-3 py-2 flex flex-col min-w-0">
      <span className="text-gray-400 text-xs uppercase tracking-wide">{label}</span>
      <span className="text-white text-lg font-semibold truncate">
        {value ?? '--'}{unit && <span className="text-gray-400 text-sm ml-1">{unit}</span>}
      </span>
    </div>
  );
}

const HELP_ITEMS = [
  { label: 'CPU', desc: 'Загрузка CPU: сервер + все дочерние процессы (docker exec, ros2 CLI). Норма: < 5%' },
  { label: 'RSS', desc: 'Физическая память: сервер + дочерние процессы. Норма: 50\u2013200 МБ. Постоянный рост = утечка' },
  { label: 'Exec', desc: 'Активные разовые docker exec команды (ros2 node list и т.д.). Норма: 0\u20133' },
  { label: 'Streams', desc: 'Активные потоковые подпроцессы (ros2 topic echo). 1 на каждый открытый лог-стрим' },
  { label: 'WebSockets', desc: 'Активные подключения браузера. 1\u20133 на каждую открытую вкладку (status + alerts + logs)' },
  { label: 'Uptime', desc: 'Время работы сервера с последнего перезапуска' },
  { label: 'Commands', desc: 'Всего команд выполнено с момента запуска сервера' },
  { label: 'Children', desc: 'Активные дочерние процессы (docker exec). Высокое число = много параллельных ROS2 команд' },
];

export function AppStats() {
  const { stats } = useSystemStats(true);
  const [showHelp, setShowHelp] = useState(false);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
            App Stats
          </h2>
          <button
            onClick={() => setShowHelp(!showHelp)}
            className={`w-5 h-5 rounded-full text-xs flex items-center justify-center transition-colors ${
              showHelp
                ? 'bg-blue-500 text-white'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-300'
            }`}
            title="Metrics help"
          >
            ?
          </button>
        </div>

        {showHelp && (
          <div className="mb-3 bg-gray-800 border border-gray-600 rounded p-3 text-xs select-text">
            <table className="w-full">
              <tbody>
                {HELP_ITEMS.map((item) => (
                  <tr key={item.label} className="border-b border-gray-700 last:border-0">
                    <td className="py-1.5 pr-3 text-blue-400 font-medium whitespace-nowrap align-top">{item.label}</td>
                    <td className="py-1.5 text-gray-300">{item.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="grid grid-cols-4 gap-3">
          <StatCard label="CPU" value={stats?.process?.cpu_percent?.toFixed(1)} unit="%" />
          <StatCard label="RSS" value={stats?.process?.rss_mb?.toFixed(0)} unit="MB" />
          <StatCard label="Exec" value={stats?.subprocesses?.active_exec} />
          <StatCard label="Streams" value={stats?.subprocesses?.active_streams} />
          <StatCard label="WebSockets" value={stats?.websockets?.total} />
          <StatCard label="Uptime" value={formatUptime(stats?.uptime_seconds)} />
          <StatCard label="Commands" value={stats?.subprocesses?.total_commands} />
          <StatCard label="Children" value={stats?.process?.children} />
        </div>
      </div>
    </div>
  );
}
