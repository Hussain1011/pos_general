import frappe
from frappe.utils import flt


CASH_MOP = "Cash"
CARD_MOPS = {"Credit Card"}
COMPLIMENTARY_MOP = "Complimentory"
CREDIT_MOP = "Credit"
TIP_FIELD = "tip"
COMPLIMENTARY_ITEM_FIELD = "custom_is_complimentary_item"  # new field name


def execute(filters=None):
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    if not company or not from_date or not to_date:
        frappe.throw("Please select Company, From Date, and To Date")

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "company": company,
            "posting_date": ["between", [from_date, to_date]],
        },
        fields=[
            "name",
            "posting_date",
            "company",
            "resturent_type",
            "base_total",
            "base_discount_amount",
            "base_net_total",
            "grand_total",
            "change_amount",
            "tip",
            "outstanding_amount",
        ],
        order_by="posting_date asc, name asc",
    )

    if not invoices:
        return get_columns(), []

    # preload all payments
    names = [i.name for i in invoices]
    payments = frappe.get_all(
        "Sales Invoice Payment",
        filters={"parent": ("in", names)},
        fields=["parent", "mode_of_payment", "amount"],
    )

    # group payments by invoice
    pay_by_inv = {}
    for p in payments:
        pay_by_inv.setdefault(p.parent, []).append(p)

    dine_in_sales = 0.0
    takeaway_sales = 0.0
    discount_total = 0.0
    cash_tips = 0.0
    card_tips = 0.0
    payment_totals = {}
    complimentary_total = 0.0
    credit_sales_total = 0.0

    def add_pay(mop, amount):
        if not mop:
            return
        payment_totals[mop] = payment_totals.get(mop, 0.0) + flt(amount)

    for inv in invoices:
        inv_pays = pay_by_inv.get(inv.name, [])
        mop_set = {p.mode_of_payment for p in inv_pays}
        inv_tip = flt(inv.tip)

        # --- Tip allocation ---
        cash_tip_this_inv = 0.0
        card_tip_this_inv = 0.0
        if inv_tip:
            if len(mop_set) == 1:
                only_mop = list(mop_set)[0]
                if only_mop in CARD_MOPS:
                    card_tip_this_inv = inv_tip
                else:
                    cash_tip_this_inv = inv_tip
            else:
                cash_tip_this_inv = inv_tip

        cash_paid = sum(flt(p.amount) for p in inv_pays if p.mode_of_payment == CASH_MOP)
        card_paid = sum(flt(p.amount) for p in inv_pays if p.mode_of_payment in CARD_MOPS)

        # --- Effective payments ---
        effective_cash = max(0.0, flt(cash_paid) - flt(inv.change_amount))
        effective_card = flt(card_paid)

        effective_other = 0.0
        for p in inv_pays:
            if p.mode_of_payment not in CARD_MOPS and p.mode_of_payment != CASH_MOP and p.mode_of_payment != COMPLIMENTARY_MOP:
                effective_other += flt(p.amount)

        effective_non_comp_paid = effective_cash + effective_card + effective_other

        # --- Complimentary from payment MOP ---
        complimentary_from_mop = 0.0
        complimentary_from_mop = max(0.0, flt(inv.grand_total) - effective_non_comp_paid)

        if mop_set and mop_set.issubset({COMPLIMENTARY_MOP}):
            complimentary_from_mop = flt(inv.grand_total)

        # --- Complimentary from items ---
        comp_items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name, COMPLIMENTARY_ITEM_FIELD: 1},
            fields=["amount"],
        )
        complimentary_from_items = sum(flt(i.amount) for i in comp_items)

        complimentary_for_this_invoice = flt(complimentary_from_mop) + flt(complimentary_from_items)
        complimentary_total += complimentary_for_this_invoice

        # --- Credit sales detection ---
        credit_for_this_invoice = 0.0
        if mop_set and CREDIT_MOP in mop_set:
            credit_for_this_invoice = flt(inv.grand_total)
        elif flt(inv.outstanding_amount) > 0.0001 and not mop_set:
            credit_for_this_invoice = flt(inv.grand_total)

        if credit_for_this_invoice > 0:
            credit_sales_total += credit_for_this_invoice

        # --- Dine In / Take Away ---
        net_sales_for_invoice = max(0.0, flt(inv.base_total) - flt(complimentary_for_this_invoice))
        if inv.resturent_type == "Dine In":
            dine_in_sales += net_sales_for_invoice
        elif inv.resturent_type == "Take Away":
            takeaway_sales += net_sales_for_invoice
        discount_total += flt(inv.base_discount_amount)

        # --- Payment totals (cash, card, other) ---
        cash_amount_final = max(0.0, cash_paid - flt(inv.change_amount)) + cash_tip_this_inv
        if abs(cash_amount_final) > 0.0001:
            add_pay(CASH_MOP, cash_amount_final)

        card_amount_final = card_paid + card_tip_this_inv
        if abs(card_amount_final) > 0.0001:
            add_pay("Card", card_amount_final)

        other_mops = [p for p in inv_pays if p.mode_of_payment not in CARD_MOPS and p.mode_of_payment != CASH_MOP]
        for p in other_mops:
            add_pay(p.mode_of_payment, flt(p.amount))

    gross_sales = dine_in_sales + takeaway_sales
    net_sales = gross_sales - discount_total
    total_tips = cash_tips + card_tips

    # recompute tips split
    for inv in invoices:
        inv_pays = pay_by_inv.get(inv.name, [])
        mop_set = {p.mode_of_payment for p in inv_pays}
        inv_tip = flt(inv.tip)
        if not inv_tip:
            continue
        if len(mop_set) == 1 and next(iter(mop_set)) in CARD_MOPS:
            card_tips += inv_tip
        else:
            cash_tips += inv_tip

    total_tips = cash_tips + card_tips
    total_all = net_sales + total_tips

    rows = []
    rows.append({"section": "Sales Breakdown"})
    rows.append({"category": "Dine-in Sales", "amount": dine_in_sales})
    rows.append({"category": "Takeaway Sales", "amount": takeaway_sales})
    rows.append({"category": "Gross Sales", "amount": gross_sales})
    rows.append({"category": "Discounts Given", "amount": -discount_total})
    rows.append({"category": "Net Sales", "amount": net_sales})

    rows.append({"section": "Tips Summary"})
    rows.append({"category": "Cash Tips", "amount": cash_tips})
    rows.append({"category": "Card Tips", "amount": card_tips})
    rows.append({"category": "Total Tips", "amount": total_tips})
    rows.append({"category": "TOTAL", "amount": total_all})

    rows.append({"section": "Payment Breakdown (Including Tips)"})
    total_payments_row = 0.0
    for mop, amt in sorted(payment_totals.items()):
        if mop not in [COMPLIMENTARY_MOP, CREDIT_MOP]:
            rows.append({"category": mop, "amount": amt})
            total_payments_row += flt(amt)

    if credit_sales_total:
        rows.append({"category": "Credit Sales", "amount": credit_sales_total})
        total_payments_row += credit_sales_total

    rows.append({"category": "TOTAL", "amount": total_payments_row})

    rows.append({"section": "Direct Expense Summary"})
    if complimentary_total:
        rows.append({"category": "Complimentary Sales", "amount": complimentary_total})

    return get_columns(), rows


def get_columns():
    return [
        {"label": "Section", "fieldname": "section", "fieldtype": "Data", "width": 240},
        {"label": "Category", "fieldname": "category", "fieldtype": "Data", "width": 260},
        {"label": "Amount (QAR)", "fieldname": "amount", "fieldtype": "Currency", "width": 140},
    ]