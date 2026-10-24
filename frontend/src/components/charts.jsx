import { useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { fmt, hourLabel } from "../api.js";

const axis = { stroke: "var(--text-muted)", fontSize: 11, tickLine: false, axisLine: false };
const grid = <CartesianGrid stroke="var(--grid)" vertical={false} />;
const tipStyle = {
  contentStyle: { background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--text-primary)", fontWeight: 600 },
  itemStyle: { color: "var(--text-secondary)" },
};

function TableToggle({ children, rows, cols }) {
  const [table, setTable] = useState(false);
  return (
    <div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="chip" onClick={() => setTable(!table)} aria-pressed={table}>
          {table ? "Chart" : "Table"}
        </button>
      </div>
      {table ? (
        <div style={{ maxHeight: 260, overflow: "auto" }}>
          <table>
            <thead><tr>{cols.map((c) => <th key={c[0]} className={c[2] ? "num" : ""}>{c[1]}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>{cols.map((c) => <td key={c[0]} className={c[2] ? "num" : ""}>
                {c[2] ? c[2](r[c[0]]) : r[c[0]]}</td>)}</tr>))}</tbody>
          </table>
        </div>
      ) : children}
    </div>
  );
}

/** Customers out over time: median line with 10-90% band. */
export function OutageCurve({ curve, start, height = 220, marker }) {
  if (!curve?.hours?.length) return <div className="muted">No outages in this scenario.</div>;
  const data = curve.hours.map((h, i) => ({
    h, label: hourLabel(start, h), p50: curve.p50[i], band: [curve.p10[i], curve.p90[i]],
  }));
  return (
    <TableToggle rows={data.filter((_, i) => i % 6 === 0)}
      cols={[["label", "Time"], ["p50", "Customers out (median)", fmt.n]]}>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          {grid}
          <XAxis dataKey="h" {...axis} tickFormatter={(h) => hourLabel(start, h)} minTickGap={50} />
          <YAxis {...axis} tickFormatter={fmt.n} width={56} />
          <Tooltip {...tipStyle} labelFormatter={(h) => hourLabel(start, h)}
            formatter={(v, k) => (k === "band" ? [`${fmt.n(v[0])}-${fmt.n(v[1])}`, "10-90% range"] :
              [fmt.n(v), "Customers out (median)"])} />
          <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.18} isAnimationActive={false} />
          <Area dataKey="p50" stroke="var(--series-1)" strokeWidth={2} fill="none" isAnimationActive={false} />
          {marker != null && <ReferenceDot x={marker} y={0} r={0} />}
        </AreaChart>
      </ResponsiveContainer>
    </TableToggle>
  );
}

const COST_SERIES = [
  ["lost_revenue", "Lost revenue (AEP)", "var(--series-1)"],
  ["repair", "Repair cost (AEP)", "var(--series-2)"],
  ["customer_cost", "Cost to customers", "var(--series-3)"],
];

/** Stacked cost bar per scenario. */
export function CostBars({ rows, height = 300 }) {
  return (
    <TableToggle rows={rows} cols={[["name", "Scenario"], ...COST_SERIES.map(([k, l]) => [k, l, fmt.usd])]}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={10}>
          <CartesianGrid stroke="var(--grid)" horizontal={false} />
          <XAxis type="number" {...axis} tickFormatter={fmt.usd} />
          <YAxis type="category" dataKey="name" {...axis} width={190} />
          <Tooltip {...tipStyle} formatter={(v, k) => [fmt.usd(v), COST_SERIES.find((s) => s[0] === k)?.[1]]}
            cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {COST_SERIES.map(([k, l, c], i) => (
            <Bar key={k} dataKey={k} name={l} stackId="a" fill={c} stroke="var(--surface-2)" strokeWidth={2}
              radius={i === COST_SERIES.length - 1 ? [0, 4, 4, 0] : 0} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </TableToggle>
  );
}

/** Crew-count trade-off: AEP cost rises with crews, customer-side cost falls; total is U-shaped. */
export function CrewCurve({ rows, current, height = 260 }) {
  if (!rows?.length) return null;
  const data = rows.map((r) => ({ ...r, customer_side: r.customer_cost + r.lost_revenue }));
  const best = data.reduce((a, b) => (b.total < a.total ? b : a));
  return (
    <TableToggle rows={data} cols={[["crews", "Total crews"], ["repair", "Crew + equipment", fmt.usd],
      ["customer_side", "Customer cost + lost revenue", fmt.usd], ["total", "Total", fmt.usd]]}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
          {grid}
          <XAxis dataKey="crews" {...axis} />
          <YAxis {...axis} tickFormatter={fmt.usd} width={60} />
          <Tooltip {...tipStyle} labelFormatter={(c) => `${c} crews`} formatter={(v, k) => [fmt.usd(v), k]} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line dataKey="repair" name="Crew + equipment (AEP)" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 4 }}
            isAnimationActive={false} />
          <Line dataKey="customer_side" name="Customer cost + lost revenue" stroke="var(--series-3)" strokeWidth={2}
            dot={{ r: 4 }} isAnimationActive={false} />
          <Line dataKey="total" name="Total" stroke="var(--series-1)" strokeWidth={2.5} dot={{ r: 4 }}
            isAnimationActive={false} />
          <ReferenceDot x={best.crews} y={best.total} r={7} fill="none" stroke="var(--text-primary)" strokeWidth={2} />
          {current && <ReferenceDot x={current} y={data.find((d) => d.crews === current)?.total ?? 0} r={0} />}
        </LineChart>
      </ResponsiveContainer>
      <div className="small secondary">Lowest total at about <b>{best.crews} crews</b> ({fmt.usd(best.total)}).</div>
    </TableToggle>
  );
}
