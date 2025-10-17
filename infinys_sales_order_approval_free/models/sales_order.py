from odoo import models, fields, api, exceptions

class SalesOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection([
        ('draft', 'Quotation'),
        ('sent', 'Quotation Sent'),
        ('to approve', 'To Approve'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True, tracking=3, default='draft')

    approval_line_ids = fields.One2many('sales.order.approval.line', 'order_id', string='Approval Lines', readonly=True, copy=False)
    
    def _get_refresh_action(self):
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        
    def action_confirm(self):
        for order in self:
            if order.approval_line_ids and any(line.status in ('pending', 'current') for line in order.approval_line_ids):
                raise exceptions.UserError("This order is already waiting for approval. Please use the approval buttons in the 'Approval Details' tab.")

            required_levels = self.env['sales.approval.level'].search([
                ('minimum_amount', '<=', order.amount_total),
                '|',
                ('maximum_amount', '>=', order.amount_total),
                ('maximum_amount', '=', 0)
            ], order='sequence asc')

            if required_levels:
                order.write({'state': 'to approve'})
                order._create_approval_lines(required_levels)
                order._check_approval_status()
                order.message_post(body="This order requires approval. The approval process has been initiated.")
            else:
                super(SalesOrder, order).action_confirm()
        return True

    def button_approve_order(self):
        self.ensure_one()
        all_approved = all(line.status == 'approved' for line in self.approval_line_ids)
        if not self.approval_line_ids or not all_approved:
            raise exceptions.UserError("The order cannot be confirmed yet. Please ensure all approval levels are completed in the 'Approval Details' tab.")
        
        self.write({
            'state': 'sale',
            'date_order': fields.Datetime.now()
        })
        return {}

    def _create_approval_lines(self, levels):
        self.approval_line_ids.unlink()
        line_vals = []
        for level in levels:
            line_vals.append((0, 0, {
                'level_id': level.id,
                'order_id': self.id,
            }))
        self.write({'approval_line_ids': line_vals})

    def _check_approval_status(self):
        self.ensure_one()
        current_line = self.approval_line_ids.filtered(lambda l: l.status == 'current')
        if current_line:
            return

        pending_lines = self.approval_line_ids.filtered(lambda l: l.status == 'pending')
        if pending_lines:
            pending_lines[0].status = 'current'
            
            activity_type_id = self.env.ref('mail.mail_activity_data_todo').id
            for user in pending_lines[0].user_ids:
                self.activity_schedule(
                    activity_type_id=activity_type_id,
                    summary=f"Approval required for Sales Order {self.name}",
                    user_id=user.id,
                    date_deadline=fields.Date.today(),
                    note=f"Please approve Sales Order {self.name} for {self.amount_total} {self.currency_id.symbol}."
                )
        else:
            self.message_post(body="All approval levels have been approved. The order can now be confirmed using the 'Approve Order' button.")
