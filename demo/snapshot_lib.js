/* 스냅샷용 통계 — 브라우저에서 **실제로 계산**한다.
 *
 * 값을 미리 박아 두면 사용자가 고를 수 있는 것이 없다. 자료를 통째로 싣고 여기서
 * 계산하면 어느 컬럼을 골라도 답이 나온다.
 *
 * 공식은 제품(statop.analyze.run)과 같은 정의를 쓴다 — 같은 자료에서 같은 수가 나와야
 * 발표에서 "이게 STATOP 가 내는 값"이라고 말할 수 있다.
 */

const S = {
  num(v) { return typeof v === "number" && isFinite(v); },

  mean(a) { return a.reduce((s, x) => s + x, 0) / a.length; },
  sd(a) {
    const m = S.mean(a);
    return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1));
  },
  quantile(sorted, q) {
    const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  },
  five(a) {
    const s = [...a].sort((x, y) => x - y);
    const q1 = S.quantile(s, .25), q2 = S.quantile(s, .5), q3 = S.quantile(s, .75);
    return { min: s[0], q1, q2, q3, max: s[s.length - 1], iqr: q3 - q1 };
  },
  skew(a) {
    const m = S.mean(a), sd = S.sd(a), n = a.length;
    if (!sd) return 0;
    return (n / ((n - 1) * (n - 2))) * a.reduce((s, x) => s + ((x - m) / sd) ** 3, 0);
  },

  /** 순위 — 동점은 평균 순위 (Spearman·Kendall 이 쓰는 그 정의) */
  ranks(a) {
    const idx = a.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]);
    const r = new Array(a.length);
    let i = 0;
    while (i < idx.length) {
      let j = i;
      while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k][1]] = avg;
      i = j + 1;
    }
    return r;
  },

  pearson(x, y) {
    const n = x.length, mx = S.mean(x), my = S.mean(y);
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      sxy += (x[i] - mx) * (y[i] - my);
      sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2;
    }
    const r = sxy / Math.sqrt(sxx * syy || 1e-300);
    const t = r * Math.sqrt((n - 2) / Math.max(1e-12, 1 - r * r));
    return { v: r, p: S.tP(Math.abs(t), n - 2) };
  },
  spearman(x, y) {
    const r = S.pearson(S.ranks(x), S.ranks(y));
    return { v: r.v, p: r.p };
  },
  kendall(x, y) {
    const n = x.length;
    let c = 0, d = 0, tx = 0, ty = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = Math.sign(x[i] - x[j]), b = Math.sign(y[i] - y[j]);
      if (a === 0 && b === 0) continue;
      if (a === 0) { tx++; continue; }
      if (b === 0) { ty++; continue; }
      a * b > 0 ? c++ : d++;
    }
    const n0 = n * (n - 1) / 2;
    const tau = (c - d) / Math.sqrt((n0 - tx) * (n0 - ty) || 1);
    // 정규근사 (scipy 의 tau-b 근사와 같은 분산)
    const z = 3 * (c - d) / Math.sqrt(n * (n - 1) * (2 * n + 5) / 2);
    return { v: tau, p: 2 * (1 - S.normCdf(Math.abs(z))) };
  },
  /** 거리상관 — 제품의 _dcor_stat 과 같은 정의, p 는 순열 */
  dcor(x, y, perms = 300, seed = 7) {
    // 제품(_dcor_stat)과 같은 식: sqrt(mean(ca·cb)) / (mean(ca²)·mean(cb²))^(1/4)
    const Ax = S._dmat(x);
    const stat = (A, b) => {
      const n = b.length, B = S._dmat(b);
      let ab = 0, aa = 0, bb = 0;
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
        ab += A[i][j] * B[i][j]; aa += A[i][j] ** 2; bb += B[i][j] ** 2;
      }
      const n2 = n * n;
      const da = aa / n2, db = bb / n2;
      return da * db > 0
        ? Math.sqrt(Math.max(0, ab / n2)) / Math.pow(da * db, 0.25) : 0;
    };
    const v = stat(Ax, y);
    let rng = seed, ge = 1;
    const rand = () => (rng = (rng * 1103515245 + 12345) % 2147483648) / 2147483648;
    for (let k = 0; k < perms; k++) {
      const sh = [...y];
      for (let i = sh.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [sh[i], sh[j]] = [sh[j], sh[i]];
      }
      if (stat(Ax, sh) >= v) ge++;
    }
    return { v, p: ge / (perms + 1) };
  },
  _dmat(a) {
    const n = a.length, M = [];
    for (let i = 0; i < n; i++) { M.push([]); for (let j = 0; j < n; j++) M[i].push(Math.abs(a[i] - a[j])); }
    const rm = M.map(r => S.mean(r)), cm = [];
    for (let j = 0; j < n; j++) cm.push(S.mean(M.map(r => r[j])));
    const gm = S.mean(rm);
    return M.map((r, i) => r.map((v, j) => v - rm[i] - cm[j] + gm));
  },

  /** Welch t — 두 군의 평균 차이 */
  welch(a, b) {
    const ma = S.mean(a), mb = S.mean(b);
    const va = S.sd(a) ** 2 / a.length, vb = S.sd(b) ** 2 / b.length;
    const t = (mb - ma) / Math.sqrt(va + vb);
    const df = (va + vb) ** 2 / (va * va / (a.length - 1) + vb * vb / (b.length - 1));
    const sp = Math.sqrt((S.sd(a) ** 2 + S.sd(b) ** 2) / 2);
    return { t, p: S.tP(Math.abs(t), df), diff: mb - ma, d: (mb - ma) / sp,
             ma, mb, sa: S.sd(a), sb: S.sd(b) };
  },
  mwu(a, b) {
    const all = [...a, ...b], r = S.ranks(all);
    const ra = r.slice(0, a.length).reduce((s, x) => s + x, 0);
    const u = ra - a.length * (a.length + 1) / 2;
    const mu = a.length * b.length / 2;
    const sg = Math.sqrt(a.length * b.length * (a.length + b.length + 1) / 12);
    const z = (u - mu) / sg;
    return { u, p: 2 * (1 - S.normCdf(Math.abs(z))), auc: u / (a.length * b.length) };
  },

  normCdf(z) {
    const t = 1 / (1 + .2316419 * Math.abs(z));
    const d = .3989423 * Math.exp(-z * z / 2);
    const p = d * t * (.3193815 + t * (-.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return z > 0 ? 1 - p : p;
  },
  /** 양측 p — 불완전 베타로 t 분포 꼬리 */
  tP(t, df) {
    const x = df / (df + t * t);
    return Math.min(1, S.ibeta(x, df / 2, .5));
  },
  ibeta(x, a, b) {
    if (x <= 0) return 0; if (x >= 1) return 1;
    const lbeta = S.lgamma(a) + S.lgamma(b) - S.lgamma(a + b);
    const front = Math.exp(Math.log(x) * a + Math.log(1 - x) * b - lbeta) / a;
    let f = 1, c = 1, d = 0;
    for (let i = 0; i <= 250; i++) {
      const m = Math.floor(i / 2);
      let num;
      if (i === 0) num = 1;
      else if (i % 2 === 0) num = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m));
      else num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1));
      d = 1 + num * d; if (Math.abs(d) < 1e-30) d = 1e-30; d = 1 / d;
      c = 1 + num / c; if (Math.abs(c) < 1e-30) c = 1e-30;
      const cd = c * d; f *= cd;
      if (Math.abs(1 - cd) < 1e-10) break;
    }
    return front * (f - 1);
  },
  lgamma(z) {
    const g = [676.5203681218851, -1259.1392167224028, 771.32342877765313,
               -176.61502916214059, 12.507343278686905, -0.13857109526572012,
               9.9843695780195716e-6, 1.5056327351493116e-7];
    if (z < .5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - S.lgamma(1 - z);
    z -= 1; let x = 0.99999999999980993;
    for (let i = 0; i < g.length; i++) x += g[i] / (z + i + 1);
    const t = z + g.length - .5;
    return .5 * Math.log(2 * Math.PI) + (z + .5) * Math.log(t) - t + Math.log(x);
  },

  hist(a, bins, lo, hi) {
    const out = new Array(bins).fill(0);
    const w = (hi - lo) / bins || 1;
    for (const v of a) out[Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / w)))]++;
    return out;
  },
  fmtP(p) { return p < 0.001 ? p.toExponential(2) : p.toFixed(4); },
  fmt(v, n = 4) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    if (v !== 0 && Math.abs(v) < 1e-4) return v.toExponential(3);
    return Number(v.toPrecision(n)).toLocaleString("en-US", { maximumSignificantDigits: n });
  },
};
