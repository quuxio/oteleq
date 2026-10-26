let _otelc_release_keys;
const _otelc_probes = require("/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/source-2b3aa91/adapters/node/src/compiler/probes.cjs");
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
      var Item = function () {
        return value;
      };
      const value = 7;
      this.value = Item();
      this.helperName = Item.name;
    } catch (_otelc_release_error) {
      _otelc_release_failed = true;
      _otelc_probes.lifetimeReleaseFailed(this, "app.Item", 1, (typeof this === "object" && this !== null || typeof this === "function") && #_otelc_owner in this ? this.#_otelc_owner() : void 0);
      throw _otelc_release_error;
    } finally {
      if (!_otelc_release_failed) _otelc_probes.lifetimeReleased(this, "app.Item", 1, (typeof this === "object" && this !== null || typeof this === "function") && #_otelc_owner in this ? this.#_otelc_owner() : void 0);
    }
  }
  #_otelc_owner() {
    return Item;
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL1VzZXJzL3NjbGFya2UvZ2l0aHViL290ZWxlcS1xdWFsaWZpY2F0aW9uLzIwMjYtMTAtMjIvY3VycmVudC1zb3VyY2UtMWY0N2M0Ni9vdGVsYy1wcjE1Ny1yZXZpZXcvbmFtZS1hZnRlci0yYjNhYTkxLW5vZGUyNi9wbGFpbi5janMiXSwic291cmNlc0NvbnRlbnQiOlsiY2xhc3MgSXRlbSB7IGNsb3NlKCkgeyBmdW5jdGlvbiBJdGVtKCkgeyByZXR1cm4gdmFsdWU7IH0gY29uc3QgdmFsdWU9NzsgdGhpcy52YWx1ZT1JdGVtKCk7IHRoaXMuaGVscGVyTmFtZT1JdGVtLm5hbWU7IH0gfVxuY29uc3QgaXRlbT1uZXcgSXRlbSgpOyBpdGVtLmNsb3NlKCk7IGNvbnNvbGUubG9nKEpTT04uc3RyaW5naWZ5KHt2YWx1ZTppdGVtLnZhbHVlLG5hbWU6aXRlbS5oZWxwZXJOYW1lfSkpOyJdLCJtYXBwaW5ncyI6Ijs7QUFBQSxNQUFNLElBQUksQ0FBQztFQUFBO0VBQUE7SUFBQTtFQUFBO0VBQUU7SUFBQTtFQUFBO0lBQUE7SUFBQTtNQUFBLElBQW1CLElBQUksZUFBRztRQUFFLE9BQU8sS0FBSztNQUFFLENBQUM7TUFBQyxNQUFNLEtBQUssR0FBQyxDQUFDO01BQUUsSUFBSSxDQUFDLEtBQUssR0FBQyxJQUFJLENBQUMsQ0FBQztNQUFFLElBQUksQ0FBQyxVQUFVLEdBQUMsSUFBSSxDQUFDLElBQUk7SUFBQztNQUFBO01BQUE7TUFBQTtJQUFBO01BQUE7SUFBQTtFQUFBO0VBQUU7SUFBQSxPQUFqSCxJQUFJO0VBQUE7RUFBQTtJQUFBO0lBQUE7SUFBQTtNQUFBO01BQUE7TUFBQTtJQUFBO01BQUE7SUFBQTtFQUFBO0FBQThHO0FBQ3hILE1BQU0sSUFBSSxHQUFDLElBQUksSUFBSSxDQUFDLENBQUM7QUFBRSxJQUFJLENBQUMsS0FBSyxDQUFDLENBQUM7QUFBRSxPQUFPLENBQUMsR0FBRyxDQUFDLElBQUksQ0FBQyxTQUFTLENBQUM7RUFBQyxLQUFLLEVBQUMsSUFBSSxDQUFDLEtBQUs7RUFBQyxJQUFJLEVBQUMsSUFBSSxDQUFDO0FBQVUsQ0FBQyxDQUFDLENBQUMiLCJpZ25vcmVMaXN0IjpbXX0=