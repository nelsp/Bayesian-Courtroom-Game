/**
 * Running probability meter and verdict display utilities.
 */
const Viz = {

  RATING_TO_PROB: {
    0: 0.001, 1: 0.02, 2: 0.1, 3: 0.2, 4: 0.35,
    5: 0.5, 6: 0.65, 7: 0.8, 8: 0.9, 9: 0.98, 10: 0.999
  },

  dbToProb(db) {
    if (db === 0) return 0.5;
    if (db > 0) return 1 - (1 / Math.pow(10, db / 10));
    return 1 / Math.pow(10, Math.abs(db) / 10);
  },

  probToDb(prob) {
    if (prob >= 0.5) return 10 * Math.log10(prob / (1 - prob));
    return -10 * Math.log10((1 - prob) / prob);
  },

  calcDbUpdate(probGuilty, probInnocent) {
    if (probInnocent <= 0) return 30;
    if (probGuilty <= 0) return -30;
    return 10 * Math.log10(probGuilty / probInnocent);
  },

  calcThresholdDb(tolerance) {
    return 10 * Math.log10(tolerance);
  },

  /** Update the running probability meter */
  updateMeter(fillId, thresholdId, valueId, currentDb, thresholdDb) {
    const prob = this.dbToProb(currentDb) * 100;
    const fill = document.getElementById(fillId);
    const thresh = document.getElementById(thresholdId);
    const val = document.getElementById(valueId);

    if (fill) fill.style.width = Math.min(100, Math.max(0, prob)) + '%';

    if (thresh) {
      const threshProb = this.dbToProb(thresholdDb) * 100;
      thresh.style.left = Math.min(100, Math.max(0, threshProb)) + '%';
    }

    if (val) val.textContent = prob.toFixed(2) + '%';
  },

  /** Format dB with sign and color class */
  formatDb(db) {
    const sign = db >= 0 ? '+' : '';
    const cls = db > 0.5 ? 'db-positive' : db < -0.5 ? 'db-negative' : 'db-neutral';
    return { text: sign + db.toFixed(1) + ' dB', cls };
  }
};
