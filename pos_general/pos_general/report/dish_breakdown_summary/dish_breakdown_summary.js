// Copyright (c) 2024, Hussain and contributors
// For license information, please see license.txt
/* eslint-disable */


frappe.query_reports["Dish Breakdown Summary"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
        },
        {
			"fieldname":"name",
			"label": __("Branch"),
			"fieldtype": "Select",
			"options": [],
		}
    ],
    onload: function() {
        // Fetch allowed branches for the current user
        frappe.call({
            method: "pos_general.pos_general.report.dish_breakdown_summary.dish_breakdown_summary.get_user_branches",
            callback: function(response) {
                if (response.message) {
                    var allowed_branches = response.message;
                    var branch_filter = frappe.query_report.get_filter('name');
                    branch_filter.df.options = allowed_branches;
                    branch_filter.refresh();
                }
            }
        });
    }
};
