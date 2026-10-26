let _otelc_release_keys;
const _otelc_probes = require("/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/source-c9a9429/adapters/node/src/compiler/probes.cjs");
class Item {
  /*@quux.otelc.generated*/
  static {
    _otelc_probes.lifetimeType(this, "app.Item", _otelc_release_keys);
  }
  [_otelc_probes.lifetimeKey(_otelc_release_keys = [], 1, {
    ["close"]: 0
  }, true, false)]() {
    let _otelc_release_failed = false;
    try {
      var _Item = function () {
        return value;
      };
      const value = 7;
      this.value = _Item();
      this.helperName = _Item.name;
    } catch (_otelc_release_error) {
      _otelc_release_failed = true;
      _otelc_probes.lifetimeReleaseFailed(this, "app.Item", 1, Item);
      throw _otelc_release_error;
    } finally {
      if (!_otelc_release_failed) _otelc_probes.lifetimeReleased(this, "app.Item", 1, Item);
    }
  }
  constructor() {
    const _otelc_creation = _otelc_probes.lifetimeCreation();
    let _otelc_failed = false;
    try {} catch (_otelc_failure) {
      _otelc_failed = true;
      _otelc_probes.lifetimeFailed(new.target, "app.Item");
      throw _otelc_failure;
    } finally {
      if (!_otelc_failed) _otelc_probes.lifetimeAdmit(this, new.target, "app.Item", _otelc_creation);
    }
  }
}
const item = new Item();
item.close();
console.log(JSON.stringify({
  value: item.value,
  name: item.helperName
}));
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6WyJJdGVtIl0sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvbmFtZS1iZWZvcmUtYzkvcGxhaW4uY2pzIl0sInNvdXJjZXNDb250ZW50IjpbImNsYXNzIEl0ZW0geyBjbG9zZSgpIHsgZnVuY3Rpb24gSXRlbSgpIHsgcmV0dXJuIHZhbHVlOyB9IGNvbnN0IHZhbHVlPTc7IHRoaXMudmFsdWU9SXRlbSgpOyB0aGlzLmhlbHBlck5hbWU9SXRlbS5uYW1lOyB9IH1cbmNvbnN0IGl0ZW09bmV3IEl0ZW0oKTsgaXRlbS5jbG9zZSgpOyBjb25zb2xlLmxvZyhKU09OLnN0cmluZ2lmeSh7dmFsdWU6aXRlbS52YWx1ZSxuYW1lOml0ZW0uaGVscGVyTmFtZX0pKTsiXSwibWFwcGluZ3MiOiI7O0FBQUEsTUFBTSxJQUFJLENBQUM7RUFBQTtFQUFBO0lBQUE7RUFBQTtFQUFFO0lBQUE7RUFBQTtJQUFBO0lBQUE7TUFBQSxJQUFtQkEsS0FBSSxZQUFBQSxDQUFBLEVBQUc7UUFBRSxPQUFPLEtBQUs7TUFBRSxDQUFDO01BQUMsTUFBTSxLQUFLLEdBQUMsQ0FBQztNQUFFLElBQUksQ0FBQyxLQUFLLEdBQUNBLEtBQUksQ0FBQyxDQUFDO01BQUUsSUFBSSxDQUFDLFVBQVUsR0FBQ0EsS0FBSSxDQUFDLElBQUk7SUFBQztNQUFBO01BQUEseURBQS9HLElBQUk7TUFBQTtJQUFBO01BQUEsZ0ZBQUosSUFBSTtJQUFBO0VBQUE7RUFBNkc7SUFBQTtJQUFBO0lBQUE7TUFBQTtNQUFBO01BQUE7SUFBQTtNQUFBO0lBQUE7RUFBQTtBQUFDO0FBQ3hILE1BQU0sSUFBSSxHQUFDLElBQUksSUFBSSxDQUFDLENBQUM7QUFBRSxJQUFJLENBQUMsS0FBSyxDQUFDLENBQUM7QUFBRSxPQUFPLENBQUMsR0FBRyxDQUFDLElBQUksQ0FBQyxTQUFTLENBQUM7RUFBQyxLQUFLLEVBQUMsSUFBSSxDQUFDLEtBQUs7RUFBQyxJQUFJLEVBQUMsSUFBSSxDQUFDO0FBQVUsQ0FBQyxDQUFDLENBQUMiLCJpZ25vcmVMaXN0IjpbXX0=