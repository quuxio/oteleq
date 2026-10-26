let _otelc_release_keys;
import _otelc_probes from "/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/source-c9a9429/adapters/node/src/compiler/probes.cjs";
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
      var read = function () {
        return value;
      };
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvYWZ0ZXItYzlhOTQyOS9yZWxlYXNlLXBsYWluLm1qcyJdLCJzb3VyY2VzQ29udGVudCI6WyJjbGFzcyBJdGVtIHsgY2xvc2UoKXsgZnVuY3Rpb24gcmVhZCgpe3JldHVybiB2YWx1ZTt9IGNvbnN0IHZhbHVlPTc7IHRoaXMudmFsdWU9cmVhZCgpOyB9IH0gY29uc3QgaXRlbT1uZXcgSXRlbSgpOyBpdGVtLmNsb3NlKCk7Y29uc29sZS5sb2coaXRlbS52YWx1ZSk7Il0sIm1hcHBpbmdzIjoiOztBQUFBLE1BQU0sSUFBSSxDQUFDO0VBQUE7RUFBQTtJQUFBO0VBQUE7RUFBRTtJQUFBO0VBQUE7SUFBQTtJQUFBO01BQUEsSUFBa0IsSUFBSSxlQUFFO1FBQUMsT0FBTyxLQUFLO01BQUMsQ0FBQztNQUFDLE1BQU0sS0FBSyxHQUFDLENBQUM7TUFBRSxJQUFJLENBQUMsS0FBSyxHQUFDLElBQUksQ0FBQyxDQUFDO0lBQUM7TUFBQTtNQUFBLHlEQUFoRixJQUFJO01BQUE7SUFBQTtNQUFBLGdGQUFKLElBQUk7SUFBQTtFQUFBO0VBQThFO0lBQUE7SUFBQTtJQUFBO01BQUE7TUFBQTtNQUFBO0lBQUE7TUFBQTtJQUFBO0VBQUE7QUFBQztBQUFFLE1BQU0sSUFBSSxHQUFDLElBQUksSUFBSSxDQUFDLENBQUM7QUFBRSxJQUFJLENBQUMsS0FBSyxDQUFDLENBQUM7QUFBQyxPQUFPLENBQUMsR0FBRyxDQUFDLElBQUksQ0FBQyxLQUFLLENBQUMiLCJpZ25vcmVMaXN0IjpbXX0=