let _otelc_release_keys;
import _otelc_probes from "/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-01fa267/provider/adapters/node/src/compiler/probes.cjs";
class Item {
  /*@quux.otelc.generated*/
  static {
    _otelc_probes.lifetimeType(this, "app.Item", _otelc_release_keys);
  }
  [_otelc_probes.lifetimeKey(_otelc_release_keys = [], 1, {
    ["close"]: 0
  }, true, false)]() {
    var read = function () {
      return value;
    };
    let _otelc_release_failed = false;
    try {
      const value = 7;
      this.value = read();
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
console.log(item.value);
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvcmVsZWFzZS1wbGFpbi5tanMiXSwic291cmNlc0NvbnRlbnQiOlsiY2xhc3MgSXRlbSB7IGNsb3NlKCl7IGZ1bmN0aW9uIHJlYWQoKXtyZXR1cm4gdmFsdWU7fSBjb25zdCB2YWx1ZT03OyB0aGlzLnZhbHVlPXJlYWQoKTsgfSB9IGNvbnN0IGl0ZW09bmV3IEl0ZW0oKTsgaXRlbS5jbG9zZSgpO2NvbnNvbGUubG9nKGl0ZW0udmFsdWUpOyJdLCJtYXBwaW5ncyI6Ijs7QUFBQSxNQUFNLElBQUksQ0FBQztFQUFBO0VBQUE7SUFBQTtFQUFBO0VBQUU7SUFBQTtFQUFBO0lBQUEsSUFBa0IsSUFBSSxlQUFFO01BQUMsT0FBTyxLQUFLO0lBQUMsQ0FBQztJQUFBO0lBQUE7TUFBQyxNQUFNLEtBQUssR0FBQyxDQUFDO01BQUUsSUFBSSxDQUFDLEtBQUssR0FBQyxJQUFJLENBQUMsQ0FBQztJQUFDO01BQUE7TUFBQSx5REFBaEYsSUFBSTtNQUFBO0lBQUE7TUFBQSxnRkFBSixJQUFJO0lBQUE7RUFBQTtFQUE4RTtJQUFBO0lBQUE7SUFBQTtNQUFBO01BQUE7TUFBQTtJQUFBO01BQUE7SUFBQTtFQUFBO0FBQUM7QUFBRSxNQUFNLElBQUksR0FBQyxJQUFJLElBQUksQ0FBQyxDQUFDO0FBQUUsSUFBSSxDQUFDLEtBQUssQ0FBQyxDQUFDO0FBQUMsT0FBTyxDQUFDLEdBQUcsQ0FBQyxJQUFJLENBQUMsS0FBSyxDQUFDIiwiaWdub3JlTGlzdCI6W119