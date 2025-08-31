// Copyright (c) 2025, Hussain and contributors
// For license information, please see license.txt

frappe.query_reports["Daily Sales and Payment Report"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		  },
		  {
			fieldname: "date",
			label: __("Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		  },
	]
};

/* eslint-disable */
