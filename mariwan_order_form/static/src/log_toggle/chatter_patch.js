import { Chatter } from "@mail/chatter/web_portal_project/chatter";

import { proxy } from "@odoo/owl";

import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";

const STORAGE_KEY = "mariwan.log_collapsed";

/** Arrow button on the side log (chatter) to hide / show it; remembered per browser. */
patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.mariwanLog = proxy({ collapsed: browser.localStorage.getItem(STORAGE_KEY) === "1" });
    },
    mariwanToggleLog() {
        this.mariwanLog.collapsed = !this.mariwanLog.collapsed;
        browser.localStorage.setItem(STORAGE_KEY, this.mariwanLog.collapsed ? "1" : "0");
    },
});
