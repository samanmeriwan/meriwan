import { isMobileOS } from "@web/core/browser/feature_detection";
import { patch } from "@web/core/utils/patch";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

/**
 * On a computer with a narrow window (split screen), keep typing in dropdown fields
 * (product, customer...). Odoo's tap-to-search popup stays for phones and tablets.
 */
patch(Many2XAutocomplete.prototype, {
    get mariwanUseSearchPopup() {
        return this.uiService.isSmall && isMobileOS();
    },
});
