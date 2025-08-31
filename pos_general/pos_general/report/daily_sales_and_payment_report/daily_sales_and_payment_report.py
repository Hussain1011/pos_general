import frappe
from frappe.utils import flt

# ---- Adjust these if your labels differ ----
CASH_MOP = "Cash"
CARD_MOPS = {"Credit Card"}
COMPLIMENTARY_MOP = "Complimentory"   # exact MOP name you use
TIP_FIELD = "tip"                      # your custom field on Sales Invoice (Currency)

def execute(filters=None):
    company = filters.get("company")
    date = filters.get("date")

    invs = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "company": company,
            "posting_date": date
        },
        fields=[
            "name",
            "posting_date",
            "company",
            "resturent_type",                 # "Dine In" / "Take Away"
            "base_total",                 # Gross (before invoice-level discount)
            "base_discount_amount",       # Invoice discount (positive)
            "base_net_total",             # After discount, before taxes
            "grand_total",              # Usually what customer pays (with round off)
            "change_amount",
            "tip"
        ],
        order_by="name"
    )

    if not invs:
        return get_columns(), []

    # Preload all payments for the selected invoices
    names = [i.name for i in invs]
    pays = frappe.get_all(
        "Sales Invoice Payment",
        filters={"parent": ("in", names)},
        fields=["parent", "mode_of_payment", "amount"]
    )

    # Index payments by invoice
    pay_by_inv = {}
    for p in pays:
        pay_by_inv.setdefault(p.parent, []).append(p)

    # Aggregates for sections
    dine_in_sales = 0.0
    takeaway_sales = 0.0
    discount_total = 0.0

    cash_tips = 0.0
    card_tips = 0.0

    payment_totals = {}  # per MOP (including tips in the proper buckets)
    complimentary_total = 0.0

    # Helper to add to payment_totals
    def add_pay(mop, amount):
        if not mop:
            return
        payment_totals[mop] = payment_totals.get(mop, 0.0) + flt(amount)

    for inv in invs:

        inv_pays = pay_by_inv.get(inv.name, [])
        sum_payments = sum(flt(p.amount) for p in inv_pays)
        mop_set = {p.mode_of_payment for p in inv_pays}

        # TIP ALLOCATION
        # - Single MOP and it's card -> card tips
        # - Split (cash+card) -> cash tips
        # - Single MOP cash -> cash tips
        inv_tip = flt(inv.tip)
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
                # split → tip goes to cash
                cash_tip_this_inv = inv_tip

        cash_paid = sum(flt(p.amount) for p in inv_pays if p.mode_of_payment == CASH_MOP)
        card_paid = sum(flt(p.amount) for p in inv_pays if p.mode_of_payment in CARD_MOPS)

        # --- Complimentary detection (new, robust) ---
        # Treat "effective" paid amounts as what truly settles the bill:
        # - Cash: subtract change given back to customer
        # - Card: full card paid
        # - Other MOPs: full amounts (exclude Complimentary itself)
        # - Tips are NOT part of settlement; they’re handled separately
        effective_cash = flt(cash_paid) - flt(inv.change_amount)
        effective_cash = max(0.0, effective_cash)  # don't let negative cash reduce settlement

        effective_card = flt(card_paid)

        effective_other = 0.0
        for p in inv_pays:
            if p.mode_of_payment not in CARD_MOPS and p.mode_of_payment != CASH_MOP and p.mode_of_payment != COMPLIMENTARY_MOP:
                effective_other += flt(p.amount)

        effective_non_comp_paid = effective_cash + effective_card + effective_other

        # Anything not covered by non-complimentary payments is complimentary
        # (This also covers partial Complimentary splits correctly.)
        complimentary_for_this_invoice = max(0.0, flt(inv.grand_total) - effective_non_comp_paid)

        # Edge case: if invoice has ONLY Complimentary MOP lines, count full invoice as complimentary
        # (In practice this will already be true from the above formula, but we keep the intent explicit.)
        if mop_set and mop_set.issubset({COMPLIMENTARY_MOP}):
            complimentary_for_this_invoice = flt(inv.grand_total)

        # Add to global aggregate
        if complimentary_for_this_invoice > 0.0001:
            complimentary_total += complimentary_for_this_invoice

        # Net sales to count in Dine In / Take Away (exclude complimentary part)
        net_sales_for_invoice = max(0.0, flt(inv.base_total) - flt(complimentary_for_this_invoice))

        # Sales Breakdown tallies
        if inv.resturent_type == "Dine In":
            dine_in_sales += net_sales_for_invoice
        elif inv.resturent_type == "Take Away":
            takeaway_sales += net_sales_for_invoice
        discount_total += flt(inv.base_discount_amount)


        # Payment Breakdown (Including Tips)
        # Cash bucket: cash_received - change + cash_tip
        cash_amount_final = cash_paid - flt(inv.change_amount) + cash_tip_this_inv
        if abs(cash_amount_final) > 0.0001:
            add_pay(CASH_MOP, cash_amount_final)

        # Card bucket: card + card_tip
        card_amount_final = card_paid + card_tip_this_inv
        if abs(card_amount_final) > 0.0001:
            # We’ll group all card-like MOPs under their actual names, so distribute:
            # If you prefer a single "Card" line, collapse them into one label.
            add_pay("Card", card_amount_final)

        # Any other MOPs (no tip logic change)
        other_mops = [p for p in inv_pays if (p.mode_of_payment not in CARD_MOPS and p.mode_of_payment != CASH_MOP)]
        for p in other_mops:
            add_pay(p.mode_of_payment, flt(p.amount))

    gross_sales = dine_in_sales + takeaway_sales
    net_sales = gross_sales - discount_total
    total_tips = cash_tips + card_tips  # we'll recompute from allocations below

    # recompute tips totals from what we allocated
    # (We already pushed tips into payment buckets. For Tips Summary we need the split.)
    # To track tips, re-loop quickly:
    for inv in invs:
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

    # Build rows exactly like your sheet
    rows = []
    # Header-like lines can be recognized in the UI by "section" value
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
    # If you want each card provider separately, keep as built;
    # If you want one "Card" line, it's already collapsed above under "Card".
    for mop, amt in sorted(payment_totals.items()):
        if mop != 'Complimentory':
            rows.append({"category": mop, "amount": amt})
            total_payments_row += flt(amt)
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