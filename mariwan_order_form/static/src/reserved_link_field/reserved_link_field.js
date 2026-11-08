import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FloatField, floatField, floatFieldProps } from "@web/views/fields/float/float_field";
import { t, useProps } from "@odoo/owl";

/**
 * Reserved quantity shown as a link: a click opens who holds that stock
 * (options="{'method': '<order form line method returning an action>'}").
 */
export class ReservedLinkField extends FloatField {
    static template = "mariwan_order_form.ReservedLinkField";
    props = useProps({
        ...floatFieldProps,
        method: t.string(),
    });

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const record = this.props.record;
        const root = record.model.root;
        if (!record.resId || (await root.isDirty())) {
            await root.save();
        }
        if (!record.resId) {
            return;
        }
        const action = await this.orm.call(record.resModel, this.props.method, [[record.resId]]);
        await this.action.doAction(action);
    }
}

export const reservedLinkField = {
    ...floatField,
    component: ReservedLinkField,
    extractProps(fieldInfo, dynamicInfo) {
        const props = floatField.extractProps(fieldInfo, dynamicInfo);
        props.method = fieldInfo.options.method;
        return props;
    },
};

registry.category("fields").add("mariwan_reserved_link", reservedLinkField);
