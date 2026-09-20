import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { DailySnapshot } from '../types';

interface Props {
  data: DailySnapshot[];
}

/**
 * 最近 N 天情绪历史图表（全部平滑曲线）
 * - 图 1：温度 + 昨日涨停今日溢价（双 Y 轴）
 * - 图 2：涨停 / 跌停 / 炸板（3 根平滑曲线）
 * - 图 3：上涨 / 下跌（2 根平滑曲线）
 */
export function HistoryChart({ data }: Props) {
  if (!data.length) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-12 text-center text-slate-500 text-sm">
        等待历史数据…
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: d.date.slice(5), // MM-DD
    fullDate: d.date,
    温度: +d.temperature.toFixed(1),
    涨停: d.limit_up_count,
    跌停: d.limit_down_count,
    炸板: d.limit_up_broken_count,
    上涨: d.rise_count,
    下跌: d.fall_count,
    昨溢价: +(d.yesterday_limit_up_avg_pcp * 100).toFixed(2),
  }));

  const totalDays = data.length;

  return (
    <div className="space-y-4">
      {/* 图 1：情绪温度 + 昨日涨停今日溢价（双轴） */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="flex items-baseline justify-between mb-3">
          <div className="text-sm font-semibold">情绪温度 · 昨日涨停今日溢价</div>
          <div className="text-xs text-slate-500">共 {totalDays} 个交易日</div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
            <YAxis
              yAxisId="left"
              stroke="#64748b"
              fontSize={11}
              tickFormatter={(v) => `${v}°`}
              domain={[0, 100]}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="#64748b"
              fontSize={11}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: '#0f172a',
                border: '1px solid #334155',
                fontSize: 12,
              }}
              labelFormatter={(label, items) => items?.[0]?.payload?.fullDate ?? label}
              formatter={(value: number, name: string) => {
                if (name === '温度') return [value.toFixed(1) + '°', name];
                if (name === '昨溢价') return [`${value.toFixed(2)}%`, name];
                return [value, name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="温度"
              stroke="#3b82f6"
              strokeWidth={2.5}
              dot={{ r: 3, fill: '#3b82f6' }}
              activeDot={{ r: 5 }}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="昨溢价"
              stroke="#10b981"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#10b981' }}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* 图 2：涨停 / 跌停 / 炸板（3 根平滑曲线） */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="text-sm font-semibold mb-3">涨跌停 · 炸板</div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
            <YAxis yAxisId="left" stroke="#64748b" fontSize={11} />
            <Tooltip
              contentStyle={{
                background: '#0f172a',
                border: '1px solid #334155',
                fontSize: 12,
              }}
              labelFormatter={(label, items) => items?.[0]?.payload?.fullDate ?? label}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="涨停"
              stroke="#ef4444"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#ef4444' }}
              activeDot={{ r: 4 }}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="跌停"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#22c55e' }}
              activeDot={{ r: 4 }}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="炸板"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#f59e0b' }}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* 图 3：上涨 / 下跌（2 根平滑曲线） */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="text-sm font-semibold mb-3">上涨 · 下跌家数</div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
            <YAxis yAxisId="left" stroke="#64748b" fontSize={11} />
            <Tooltip
              contentStyle={{
                background: '#0f172a',
                border: '1px solid #334155',
                fontSize: 12,
              }}
              labelFormatter={(label, items) => items?.[0]?.payload?.fullDate ?? label}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="上涨"
              stroke="#f87171"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#f87171' }}
              activeDot={{ r: 4 }}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="下跌"
              stroke="#86efac"
              strokeWidth={2}
              dot={{ r: 2.5, fill: '#86efac' }}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
