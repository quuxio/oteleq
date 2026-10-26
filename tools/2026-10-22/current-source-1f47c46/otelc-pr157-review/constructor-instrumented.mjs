import _otelc_probes from "/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-01fa267/provider/adapters/node/src/compiler/probes.cjs";
class Item {
  /*@quux.otelc.generated*/
  static {
    _otelc_probes.lifetimeType(this, "app.Item", []);
  }
  constructor() {
    var read = function () {
      return value;
    };
    const _otelc_creation = _otelc_probes.lifetimeCreation();
    let _otelc_failed = false;
    try {
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvY29uc3RydWN0b3ItcGxhaW4ubWpzIl0sInNvdXJjZXNDb250ZW50IjpbImNsYXNzIEl0ZW0geyBjb25zdHJ1Y3RvcigpeyBmdW5jdGlvbiByZWFkKCl7cmV0dXJuIHZhbHVlO30gY29uc3QgdmFsdWU9NzsgdGhpcy52YWx1ZT1yZWFkKCk7IH0gfSBjb25zb2xlLmxvZyhuZXcgSXRlbSgpLnZhbHVlKTsiXSwibWFwcGluZ3MiOiI7QUFBQSxNQUFNLElBQUksQ0FBQztFQUFBO0VBQUE7SUFBQTtFQUFBO0VBQUUsV0FBVztJQUFBLElBQWEsSUFBSSxlQUFFO01BQUMsT0FBTyxLQUFLO0lBQUMsQ0FBQztJQUFBO0lBQUE7SUFBQTtNQUFDLE1BQU0sS0FBSyxHQUFDLENBQUM7TUFBRSxJQUFJLENBQUMsS0FBSyxHQUFDLElBQUksQ0FBQyxDQUFDO0lBQUM7TUFBQTtNQUFBO01BQUE7SUFBQTtNQUFBO0lBQUE7RUFBQTtBQUFHO0FBQUUsT0FBTyxDQUFDLEdBQUcsQ0FBQyxJQUFJLElBQUksQ0FBQyxDQUFDLENBQUMsS0FBSyxDQUFDIiwiaWdub3JlTGlzdCI6W119