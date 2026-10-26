import _otelc_probes from "/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/source-c9a9429/adapters/node/src/compiler/probes.cjs";
class Item {
  /*@quux.otelc.generated*/
  static {
    _otelc_probes.lifetimeType(this, "app.Item", []);
  }
  constructor() {
    const _otelc_creation = _otelc_probes.lifetimeCreation();
    let _otelc_failed = false;
    try {
      var read = function () {
        return value;
      };
      const value = 7;
      this.value = read();
    } catch (_otelc_failure) {
      _otelc_failed = true;
      _otelc_probes.lifetimeFailed(new.target, "app.Item");
      throw _otelc_failure;
    } finally {
      if (!_otelc_failed) _otelc_probes.lifetimeAdmit(this, new.target, "app.Item", _otelc_creation);
    }
  }
}
console.log(new Item().value);
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvYWZ0ZXItYzlhOTQyOS9jb25zdHJ1Y3Rvci1wbGFpbi5tanMiXSwic291cmNlc0NvbnRlbnQiOlsiY2xhc3MgSXRlbSB7IGNvbnN0cnVjdG9yKCl7IGZ1bmN0aW9uIHJlYWQoKXtyZXR1cm4gdmFsdWU7fSBjb25zdCB2YWx1ZT03OyB0aGlzLnZhbHVlPXJlYWQoKTsgfSB9IGNvbnNvbGUubG9nKG5ldyBJdGVtKCkudmFsdWUpOyJdLCJtYXBwaW5ncyI6IjtBQUFBLE1BQU0sSUFBSSxDQUFDO0VBQUE7RUFBQTtJQUFBO0VBQUE7RUFBRSxXQUFXO0lBQUE7SUFBQTtJQUFBO01BQUEsSUFBYSxJQUFJLGVBQUU7UUFBQyxPQUFPLEtBQUs7TUFBQyxDQUFDO01BQUMsTUFBTSxLQUFLLEdBQUMsQ0FBQztNQUFFLElBQUksQ0FBQyxLQUFLLEdBQUMsSUFBSSxDQUFDLENBQUM7SUFBQztNQUFBO01BQUE7TUFBQTtJQUFBO01BQUE7SUFBQTtFQUFBO0FBQUc7QUFBRSxPQUFPLENBQUMsR0FBRyxDQUFDLElBQUksSUFBSSxDQUFDLENBQUMsQ0FBQyxLQUFLLENBQUMiLCJpZ25vcmVMaXN0IjpbXX0=