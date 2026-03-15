/**
 * Probability input controls — slider (0–10 rating) and direct entry.
 */
const EvidenceInput = {

  inputMethod: 'slider',

  init(method) {
    this.inputMethod = method || 'slider';
    this._bindSliders();
    this._bindDirectInputs();
    this._showActiveMethod();
  },

  setMethod(method) {
    this.inputMethod = method;
    this._showActiveMethod();
    this._recalc();
  },

  _showActiveMethod() {
    const showSlider = this.inputMethod === 'slider';
    document.getElementById('guilty-slider-container').style.display = showSlider ? '' : 'none';
    document.getElementById('guilty-direct-container').style.display = showSlider ? 'none' : '';
    document.getElementById('innocent-slider-container').style.display = showSlider ? '' : 'none';
    document.getElementById('innocent-direct-container').style.display = showSlider ? 'none' : '';
  },

  _bindSliders() {
    const gs = document.getElementById('guilty-slider');
    const is = document.getElementById('innocent-slider');
    if (gs) gs.addEventListener('input', () => this._onSliderChange());
    if (is) is.addEventListener('input', () => this._onSliderChange());
  },

  _bindDirectInputs() {
    const gd = document.getElementById('guilty-direct');
    const id = document.getElementById('innocent-direct');
    if (gd) gd.addEventListener('input', () => this._onDirectChange());
    if (id) id.addEventListener('input', () => this._onDirectChange());
  },

  _onSliderChange() {
    const gr = parseInt(document.getElementById('guilty-slider').value);
    const ir = parseInt(document.getElementById('innocent-slider').value);
    document.getElementById('guilty-slider-val').textContent = gr;
    document.getElementById('innocent-slider-val').textContent = ir;

    const gp = Viz.RATING_TO_PROB[gr];
    const ip = Viz.RATING_TO_PROB[ir];
    document.getElementById('guilty-prob-display').textContent = (gp * 100).toFixed(1) + '%';
    document.getElementById('innocent-prob-display').textContent = (ip * 100).toFixed(1) + '%';

    this._recalc();
  },

  _onDirectChange() {
    this._recalc();
  },

  _recalc() {
    if (typeof App !== 'undefined' && App.updateLiveCalc) {
      App.updateLiveCalc();
    }
  },

  getValues() {
    if (this.inputMethod === 'slider') {
      const gr = parseInt(document.getElementById('guilty-slider').value);
      const ir = parseInt(document.getElementById('innocent-slider').value);
      return {
        prob_guilty: Viz.RATING_TO_PROB[gr],
        prob_innocent: Viz.RATING_TO_PROB[ir],
        guilty_rating: gr,
        innocent_rating: ir,
        used_rating_scale: true
      };
    } else {
      let pg = parseFloat(document.getElementById('guilty-direct').value);
      let pi = parseFloat(document.getElementById('innocent-direct').value);
      pg = Math.max(0.001, Math.min(0.999, pg || 0.5));
      pi = Math.max(0.001, Math.min(0.999, pi || 0.5));
      return {
        prob_guilty: pg,
        prob_innocent: pi,
        guilty_rating: null,
        innocent_rating: null,
        used_rating_scale: false
      };
    }
  },

  reset() {
    document.getElementById('guilty-slider').value = 5;
    document.getElementById('innocent-slider').value = 5;
    document.getElementById('guilty-direct').value = 0.5;
    document.getElementById('innocent-direct').value = 0.5;
    this._onSliderChange();
  },

  adjustProb(which, delta) {
    const input = document.getElementById(which + '-direct');
    let val = parseFloat(input.value) || 0.5;
    val = Math.max(0.001, Math.min(0.999, val + delta));
    input.value = val.toFixed(3);
    this._recalc();
  }
};
