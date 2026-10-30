def post_init_hook(env):
    # Odoo loads the default chart of accounts at the end of the install
    # (registry._auto_install_template); configure the company after that.
    registry = env.registry
    load_chart = getattr(registry, '_auto_install_template', None)
    if load_chart:
        def load_chart_then_configure(env):
            load_chart(env)
            env['res.company']._mariwan_apply_configuration()
        registry._auto_install_template = load_chart_then_configure
    else:
        env['res.company']._mariwan_apply_configuration()
