export function mapTimes(weatherTimes, frames, includeWeather = true) {
  if (!weatherTimes?.length) return [];
  const start = new Date(frames?.start || weatherTimes[0]).getTime();
  const weatherEnd = new Date(weatherTimes.at(-1)).getTime();
  const lastFrame = frames?.hours?.at(-1) ?? 0;
  const weatherHours = Math.round((weatherEnd - start) / 3.6e6);
  const last = includeWeather || !frames?.hours?.length ? Math.max(weatherHours, lastFrame) : lastFrame;
  return Array.from({ length: last + 1 }, (_, h) => new Date(start + h * 3.6e6).toISOString());
}

export function restorationHour(totals) {
  if (!totals?.length) return null;
  const lastOut = totals.findLastIndex((n) => n > 0);
  return lastOut >= 0 && lastOut < totals.length - 1 ? lastOut + 1 : null;
}
