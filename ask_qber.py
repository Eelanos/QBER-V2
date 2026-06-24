# ask_qber.py
import os
from dotenv import load_dotenv
import re

load_dotenv()
import json
from openai import OpenAI
from flask import request, jsonify

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# These get set when init() is called from app.py
_app = None
_fetch_data = None

def init(app, fetch_data):
    """Called from app.py to register the route and inject dependencies."""
    global _app, _fetch_data
    _app = app
    _fetch_data = fetch_data



    @app.route('/api/ask-qber', methods=['POST'])
    def ask_qber():

        data = request.get_json()

        if not data or not data.get('question', '').strip():
            return jsonify({"error": "Please provide a question."}), 400

        question = data['question'].strip()
        conversation_history = data.get('conversation_history', [])

        if not is_valid_business_query(question):
            return jsonify({
                "summary": "Please ask a business analytics question related to sales, revenue, profitability, customers, products, inventory, or trends.",
                "chart": None,
                "table": []
            })

        sql = None

        try:
            sql = call_openai_sql(question, conversation_history)
            print(f"[Ask QBER] SQL Generated: {sql}")

            if "oee_data" in sql.lower():
                print("USING OEE TABLE")

            if "hppl_budget" in sql.lower():
                print("USING BUDGET TABLE")

            df = _fetch_data(sql)

            if df.empty:
                return jsonify({
                    "summary": "No data found for your question. Try adjusting the filters — check if the product name, segment, or time period exists in the data.",
                    "chart": None,
                    "sql_used": sql,
                    "row_count": 0
                })

            rows    = df.fillna(0).to_dict(orient='records')
            columns = list(df.columns)

            question_lower = question.lower()

            if any(x in question_lower for x in ['month over month', 'month-over-month', 'mom', 'MoM', 'monthly growth']):
                result = build_mom_chart_response(rows)
            elif any(x in question_lower for x in ['year over year', 'year-over-year', 'yoy', 'YoY']):
                result = build_yoy_chart_response(rows)
            else:
                intent = extract_query_intent(question)
                print("INTENT:", intent)
                result = call_openai_response(
                    question,
                    sql,
                    columns,
                    rows,
                    conversation_history,
                    intent
                )

            return jsonify({
                "summary":   result.get("summary", ""),
                "chart":     result.get("chart", None),
                "sql_used":  sql,
                "row_count": len(rows)
            })

        except ValueError as e:
            return jsonify({
                "summary": "I couldn’t confidently answer this question. Please try rephrasing.",
                "chart": None,
                "table": []
            }), 200

        except json.JSONDecodeError:
            return jsonify({
                "summary": "I couldn’t confidently answer this question. Please try rephrasing.",
                "chart": None,
                "table": []
            }), 200



        except Exception as e:

            print(f"[Ask QBER] Error: {e}")

            error_str = str(e).lower()

            if any(x in error_str for x in ['unknown column', 'doesn\'t exist', 'no such table', 'operationalerror', 'table', 'column', 'field list', 'syntax', 'sql']):
                return jsonify({
                    "summary": "Your database does not have this information.",
                    "chart": None,
                    "table": [],
                    "sql_used": sql or "SQL not generated"
                }), 200

            return jsonify({
                "summary": "I couldn’t confidently answer this question. Please try rephrasing.",
                "chart": None,
                "table": [],
                "sql_used": sql or "SQL not generated"
            }), 200

# ─── Schema Context for OpenAI ────────────────────────────────────────────────
SCHEMA_CONTEXT = """
You are a MySQL expert working with a business analytics portal called QBER.
The data belongs to a manufacturing/packaging company.

You have access to FIVE tables in the database. Pick the correct table based on the user's question.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 1: pc_analysis_data  — main P&L / sales / cost data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIMENSION COLUMNS (plain text, no casting needed):
- year              : Calendar year e.g. "2023"
- fy                : Financial year stored as numeric values (2024, 2025)
- month             : Month name e.g. "APR", "MAY", "JUN"
- bu                : Business Unit name
- plant             : Manufacturing plant name
- customers         : Customer name
- mkt_segment       : Market segment
- mkt_sub_segment   : Market sub-segment
- product_group     : Product group name
- products          : Individual product name

METRIC COLUMNS (stored as VARCHAR with commas — ALWAYS cast before any math):
- qty_sqm               : Quantity in square meters (volume)
- sales                 : Total sales / revenue value
- ind_va                : Industrial Value Addition
- ind_ebit              : EBIT (Earnings Before Interest and Tax) — key profitability metric
- cost_printing         : Printing process cost
- cost_lamination       : Lamination process cost
- cost_hotmelt          : Hotmelt process cost
- cost_metalling        : Metalling process cost
- cost_embossing        : Embossing process cost
- cost_jobwork          : Job work cost
- cost_slitting         : Slitting process cost
- cost_packing          : Packing cost
- cost_cost_to_serve    : Cost to serve
- rm                    : Raw material cost
- consumables           : Consumables cost

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 2: closing_stock  — inventory snapshot (closing stock position)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIMENSION COLUMNS:
- fy            : Financial year e.g. "FY24", "FY25"
- month         : Month name e.g. "APR", "MAY"
- plant         : Manufacturing plant name
- bu            : Business Unit name

METRIC COLUMNS (VARCHAR with commas — ALWAYS cast before any math):
- qty           : Stock quantity
- unit_price    : Price per unit
- amount        : Total closing stock value (qty × unit_price)
- non_moving    : Value of non-moving stock (zero consumption)
- slow_moving   : Value of slow-moving stock
- inventory_days: Number of days of inventory held (higher = more stock tied up)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 3: stock_ageing  — stock age bucket breakdown
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIMENSION COLUMNS:
- fy        : Financial year
- month     : Month name
- plant     : Manufacturing plant name
- bu        : Business Unit name

METRIC COLUMNS (VARCHAR with commas — ALWAYS cast before any math):
- qty           : Total stock quantity
- unit_price    : Price per unit
- amount        : Total stock value
- below_30      : Value of stock aged below 30 days
- `30_to_60`    : Value of stock aged 30–60 days
- `60_to_90`    : Value of stock aged 60–90 days
- above_90      : Value of stock aged above 90 days

CRITICAL: Column names 30_to_60 and 60_to_90 start with digits.
ALWAYS wrap them in backticks in your SQL: `30_to_60`, `60_to_90`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 4: hppl_budget — Sales & EBIT Budget Data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION COLUMNS:
- year
- fy
- month
- bu
- plant
- customers
- mkt_segment
- product_group
- product

BUDGET METRICS:
- Sales_Budget
- Ebit_Budget

IMPORTANT:
Sales_Budget and Ebit_Budget are monetary values.

Always convert them to Crores:
ROUND(
SUM(CAST(REPLACE(Sales_Budget, ',', '') AS DECIMAL(18,2)))
/10000000,
2
)
ROUND(
SUM(CAST(REPLACE(Ebit_Budget, ',', '') AS DECIMAL(18,2)))
/10000000,
2
)

Use this table whenever the user asks:
- budget
- budgeted sales
- budgeted EBIT
- sales budget
- EBIT budget
- budget vs actual
- variance to budget

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 5: oee_data — Manufacturing OEE Data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION COLUMNS:
- Year
- FY
- Month
- Month No
- Date
- Plant
- Process
- Resources

METRIC COLUMNS:
- Run_Time_ACT
- ACT_Jco
- P_Maint
- Act
- Std_Output_Mtr_
- Defect_Kms
- Down_Time_ACT
- Wkg_for_Quality
- Rated_Speed
- Time_Taken_to_produce_at_rated_speed
- No_Work

Use this table whenever the user asks:
- OEE
- machine utilization
- downtime
- production efficiency
- machine performance
- resource performance
- defect
- defect kms
- plant efficiency
- process efficiency
- availability
- quality losses

For ranking questions containing:
* highest
* top
* best
* leading
* largest
and no specific number is provided,
default to: LIMIT 10

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONEY OUTPUT RULE (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Whenever returning any monetary value, ALWAYS convert it to Crores.

Monetary columns include:
- sales
- ind_va
- ind_ebit
- rm
- consumables
- amount
- unit_price
- all cost_ columns

Use:

ROUND(
SUM(CAST(REPLACE(column_name, ',', '') AS DECIMAL(18,2)))
/ 10000000,
2
)

Example:

SELECT customers,
ROUND(
SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2)))
/ 10000000,
2
) AS total_sales_cr
FROM pc_analysis_data
GROUP BY customers

Never return raw rupee values.
Always return Crores for monetary outputs.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES THAT APPLY TO ALL THREE TABLES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ALL numeric columns across all tables are VARCHAR with commas (e.g. "1,23,456.78").
   ALWAYS use: CAST(REPLACE(column_name, ',', '') AS DECIMAL(18,2))
   for ANY numeric operation — SUM, AVG, comparison, arithmetic, everything.
2. Only write SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or ALTER.
3. Always use GROUP BY when using aggregate functions.
4. Default ORDER BY the most relevant metric DESC.
5. Choose LIMIT smartly based on the question:
   - "Top 10" → LIMIT 10
   - "Top 5" → LIMIT 5  
   - User specifies a number → use that number
   - List questions like "which products", "which customers" with no number specified → NO LIMIT, return all
   - Never add an arbitrary LIMIT that would cut off a complete list the user asked for
6. Return ONLY the raw SQL query — no explanation, no markdown, no backticks.
7. ALWAYS backtick `30_to_60` and `60_to_90` when querying stock_ageing.

TABLE SELECTION GUIDE — pick the right table:
- Questions about sales, revenue, EBIT, margins, costs, customers, products → pc_analysis_data
- Questions about closing stock, inventory value, inventory days, non-moving/slow-moving stock → closing_stock
- Questions about stock age, ageing buckets, above-90-day stock → stock_ageing
- Questions about Budget, Budget vs Actual, Variance → hppl_budget
- Questions about OEE, Downtime, Defects, Machine Utilization, Plant Performance → oee_data


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROWTH INTERPRETATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The word "growth" means comparison between periods.
Never interpret growth as:
- EBIT
- EBIT %
- Margin %
- Profitability
- Sales ranking
unless the user explicitly asks for those metrics.

When the user asks:
- highest growth
- fastest growing
- growth drivers
- growth by product
- growth by customer
- growth by segment
- growth by plant
and does not specify a metric,
assume:
Growth = Sales Growth.
Growth questions MUST compare: Current FY vs Previous FY

using:
Current FY = MAX(fy)
Previous FY = MAX(fy)-1
Growth Value = Current Year Sales - Previous Year Sales
Growth % = ((Current Year Sales - Previous Year Sales)/ Previous Year Sales) * 100

Never answer a growth question using:
- single year sales
- EBIT ranking
- EBIT %
- margin %
Growth always requires two periods.

IMPORTANT:
Sales Growth is a monetary metric.
Whenever Growth Value is calculated:
Growth Value = Current Year Sales - Previous Year Sales
the result MUST be converted to Crores.
Example:
ROUND((Current Year Sales-Previous Year Sales)/10000000,2) AS growth_cr
Current Year Sales and Previous Year Sales
must also be converted to Crores.
Never return raw growth values.
Always return:
current_year_sales_cr
previous_year_sales_cr
growth_cr
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUSINESS QUESTION INTERPRETATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Questions asking:
"highest EBIT this year and change versus last year"
require:
* current year EBIT
* previous year EBIT
* EBIT change

Questions asking:
"highest revenue but lowest margin"
require:
* revenue
* margin %

Questions asking:
"top profit making and loss making customers"
require:
* positive EBIT ranking
* negative EBIT ranking

Questions asking:
"why did EBIT decline"
require:
* comparison between periods
* EBIT
* sales
* costs

Never answer a comparison question using a single period.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIME INTELLIGENCE RULES (VERY IMPORTANT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The dataset contains:
* fy = 2024, 2025
* year = 2023, 2024, 2025

Interpret user time references as:
* "this year" → latest fy available in the data
* "last year" → previous fy available in the data
* "current year" → latest fy
* "previous year" → previous fy
* "YoY" → compare latest fy vs previous fy
* "versus last year" → compare latest fy vs previous fy

For this dataset:
Current FY = MAX(fy)
Previous FY = MAX(fy)-1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUDGET VS ACTUAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks:
- budget vs actual
- variance
- variance to budget
- sales vs budget
- EBIT vs budget

Use:
actual values → pc_analysis_data
budget values → hppl_budget

Join using:
fy
month
plant
customers
product_group

Return:
budget value
actual value
variance

Variance =
actual - budget

Always convert monetary values to Crores.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONTH-OVER-MONTH RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When the user asks:
- month over month
- MoM
- monthly growth
- monthly trend
- revenue trend by month
- sales trend by month
Compare each month against the immediately previous month.

Examples:
APR vs MAR
MAY vs APR
JUN vs MAY
Do NOT compare FY2025 vs FY2024. Do NOT use current year and previous year logic. Month-over-month means comparison between consecutive months.

For month-over-month questions: Do NOT use: LAG(), LEAD(), OVER()
Return monthly sales only.

Example:
SELECT
month,
ROUND(
SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2)))
/10000000,
2
) AS sales_cr
FROM pc_analysis_data
WHERE fy = (SELECT MAX(fy) FROM pc_analysis_data)
GROUP BY month
ORDER BY FIELD(
month,
'APR','MAY','JUN','JUL','AUG','SEP',
'OCT','NOV','DEC','JAN','FEB','MAR'
);
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YEAR-OVER-YEAR COMPARISON RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When the user asks:
* compared to last year
* versus last year
* year over year
* YoY
* growth vs previous year
* decline vs previous year
* change from last year
ALWAYS return BOTH years in the same row.

Example:
SELECT
customers,

SUM(
CASE WHEN fy = 2025
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
) AS current_year,

SUM(
CASE WHEN fy = 2024
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
) AS previous_year,

(
SUM(
CASE WHEN fy = 2025
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
-

SUM(
CASE WHEN fy = 2024
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
) AS change_value

FROM pc_analysis_data
GROUP BY customers

Never GROUP BY year for comparison questions.
Always calculate change in the SQL itself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONETARY COMPARISON RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When comparison queries involve monetary fields such as:
- sales
- ind_ebit
- ind_va
- rm
- consumables
- amount
- any cost_ column
ALWAYS convert EACH calculated output to Crores.

Example:
SELECT customers, 
ROUND(
SUM(
CASE WHEN fy = 2025
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
/10000000, 2) AS ebit_2025_cr,

ROUND(
SUM(
CASE WHEN fy = 2024
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
/10000000,
2
) AS ebit_2024_cr,

ROUND(
(
SUM(
CASE WHEN fy = 2025
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
-
SUM(
CASE WHEN fy = 2024
THEN CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))
ELSE 0
END
)
)
/10000000,
2
) AS change_cr
FROM pc_analysis_data
GROUP BY customers
ORDER BY ebit_2025_cr DESC
LIMIT 10;

DERIVED METRICS YOU CAN COMPUTE:
- Total processing cost     = SUM of all cost_ columns (pc_analysis_data)
- EBIT % = ROUND(
               (SUM(CAST(REPLACE(ind_ebit,',','') AS DECIMAL(18,2))) /
                NULLIF(SUM(CAST(REPLACE(sales,',','') AS DECIMAL(18,2))), 0)
               ) * 100, 2)
- VA % (Contribution Margin) = ROUND((SUM(ind_va) / NULLIF(SUM(sales), 0)) * 100, 2)
- Direct cost = sales - ind_va

CRITICAL RULES FOR PERCENTAGE CALCULATIONS:
1. ALWAYS use NULLIF(..., 0) on the denominator to prevent division by zero
2. Only when calculating a percentage metric (EBIT%, VA%, Margin%, Contribution%, Risk%)
add: HAVING SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) > 1000000
Do NOT add this HAVING clause for revenue rankings, customer rankings, product rankings, sales reports, or non-percentage calculations.
3. ALWAYS use ROUND(..., 2) on percentage results
4. NEVER hardcode years unless explicitly mentioned by the user.
For "this year" use:
WHERE fy = (
    SELECT MAX(fy)
    FROM pc_analysis_data
)
For "last year" use:
WHERE fy = (
    SELECT MAX(fy)-1
    FROM pc_analysis_data
)
5. When user asks for EBIT%, always show both the EBIT% AND total sales together
   so the user can judge the result in context
   
- RM + Consumables          = rm + consumables (both cast first)
- Dead stock risk %         = non_moving / amount * 100  (closing_stock)
- Ageing risk %             = above_90 / amount * 100    (stock_ageing)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES FOR LIST-TYPE QUESTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- NEVER return a list of names only with no numeric metric.
- If user asks "which products does X buy" or "list customers" or "what did X purchase":
  ALWAYS include total_sales (or relevant metric) alongside the names.
- ALWAYS use GROUP BY on the name column so duplicates across months/years are collapsed.
- ALWAYS add HAVING SUM(CAST(REPLACE(sales,',','') AS DECIMAL(18,2))) > 0
  to filter out products/customers with zero or negligible sales.
- Example for "which products does Mondelez buy":

  SELECT products,
       ROUND(
       SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2)))
       / 10000000,
       2
       ) AS total_sales_cr
  FROM pc_analysis_data
  WHERE customers LIKE '%MONDELEZ%'
  GROUP BY products
  HAVING SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) > 0
  ORDER BY total_sales_cr DESC;
  
EXAMPLE QUERIES:

-- Sales & EBIT by product
SELECT products,
    
    ROUND(
    SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2)))
    / 10000000,
    2
    ) AS total_sales_cr,
    
    ROUND(
    SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2)))
    / 10000000,
    2
    ) AS total_ebit_cr
FROM pc_analysis_data
GROUP BY products
ORDER BY total_ebit DESC
LIMIT 10;

-- Closing stock value and inventory days by plant
SELECT plant,
       ROUND(
        SUM(CAST(REPLACE(amount, ',', '') AS DECIMAL(18,2)))
        / 10000000,
        2
        ) AS total_stock_value_cr
       AVG(CAST(REPLACE(inventory_days, ',', '') AS DECIMAL(18,2))) AS avg_inventory_days
FROM closing_stock
GROUP BY plant
ORDER BY total_stock_value DESC;

-- Stock ageing breakdown by BU (note backticks on digit-start columns)
SELECT bu,
       ROUND(
        SUM(CAST(REPLACE(amount, ',', '') AS DECIMAL(18,2)))
        / 10000000,
        2
        ) AS total_amount_cr
       SUM(CAST(REPLACE(below_30, ',', '') AS DECIMAL(18,2))) AS aged_below_30,
       SUM(CAST(REPLACE(`30_to_60`, ',', '') AS DECIMAL(18,2))) AS aged_30_to_60,
       SUM(CAST(REPLACE(`60_to_90`, ',', '') AS DECIMAL(18,2))) AS aged_60_to_90,
       SUM(CAST(REPLACE(above_90, ',', '') AS DECIMAL(18,2))) AS aged_above_90
FROM stock_ageing
GROUP BY bu
ORDER BY aged_above_90 DESC;

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SQL EXECUTION CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The application can execute ONLY ONE SQL statement.

NEVER generate:
SELECT ...;
SELECT ...;
For questions asking for both profit and loss customers: Return one combined result set. Never generate multiple SELECT statements.

When the user asks for:
- profit-making and loss-making
- gainers and losers
- best and worst
- top and bottom
Return BOTH categories in a single result set.
Do not generate multiple SQL statements.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROFIT AND LOSS CUSTOMER RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For questions asking:
- profit-making customers
- loss-making customers
- profitable customers
- unprofitable customers
- top profit customers
- top loss customers

Always calculate:
SUM(ind_ebit)
per customer first.

Then classify:
Profit Customer:
SUM(ind_ebit) > 0

Loss Customer:
SUM(ind_ebit) < 0

Never use:
CASE WHEN ind_ebit > 0
CASE WHEN ind_ebit < 0
on individual rows.
Classification must be based on total aggregated EBIT.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOP PROFIT AND LOSS QUESTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user asks:
- top profit-making and loss-making customers
- top gainers and losers
- best and worst customers
Return ONE result set.

Use:
CASE
WHEN SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) > 0
THEN 'Profit'
ELSE 'Loss'
END AS customer_type

Include:
customer
total_ebit_cr
customer_type

Do NOT generate multiple SELECT statements.
Order by:
ABS(total_ebit_cr) DESC
so both large profit and large loss customers appear.


ENTITY DRILL-DOWN RULE:
When the user asks:
- products for highest customer
- products bought by top customer
- products for top plant
- products in highest segment
DO NOT answer directly.
Step 1: Identify the highest entity first.
Step 2: Filter the dataset to that entity.
Step 3: Generate the requested breakdown.

Example:
Question:
"What are the top 10 products for the highest customer?"
Correct logic:
1. Find customer with highest sales.
2. Filter rows for that customer.
3. Group by products.
4. Return top 10 products.
Never aggregate products across all customers.

ENTITY CONTEXT RULE:
When a query identifies an entity first and then returns a breakdown, the identified entity must be included in the final result set.

Examples:
- Top products for highest customer
- Top products for highest plant
- Top customers in highest segment
- Products bought by MONDELEZ
Include the parent entity column in the SELECT statement so it can be referenced in the narrative summary.
"""

CHART_RULES = """
Choose chart type based on the data:
- Comparing named categories (products, customers, segments, plants) → "bar"
- Trend over time (monthly, yearly sequence) → "line"
- Cost breakdown / composition / share → "doughnut"
- Top N ranking → "bar" (horizontal feel, still use bar type)
- Single number result or 1 row → set chart to null, summary only

WHEN TO SET CHART TO NULL — very important:
- If the result has ONLY name/label columns and no numeric metric → null
- If all data values would be equal (e.g. 1,1,1,1) because there's nothing to measure → null
- If the question is a yes/no or purely factual → null
- If only 1 data point exists → null
- A chart is only useful when there is a meaningful numeric DIFFERENCE between items.
  If there is nothing to compare visually, do not generate a chart.

MONETARY DATA RULE:
- Any monetary column ending in "_cr" is already in Crores.
- Use those values exactly as provided.
- Never scale or convert them.
"""
def is_valid_business_query(question):
    q = question.lower().strip()
    if len(q) < 3:
        return False
    invalid_inputs = [ "hi", "hello", "hey", "test", "ok", "hii"]
    if q in invalid_inputs:
        return False
    return True

def call_openai_sql(question: str, conversation_history: list) -> str:
    """
    OpenAI Call #1 — Converts natural language question to a MySQL SELECT query.
    Uses gpt-4o-mini (fast + cheap, good enough for SQL).
    """
    # Include last few exchanges for follow-up question context
    history_context = ""
    if conversation_history:
        history_context = "\n\nRecent conversation (for context on follow-up questions):\n"
        for msg in conversation_history[-4:]:
            history_context += f"{msg['role'].upper()}: {msg['content']}\n"

    question_lower = question.lower()

    intent = extract_query_intent(question)

    if intent["analysis_type"] == "profit_risk":
        return """
        SELECT
            customers,

            ROUND(
                SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) / 10000000,
                2
            ) AS total_sales_cr,

            ROUND(
                SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) / 10000000,
                2
            ) AS total_ebit_cr,

            ROUND(
                (
                    SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2)))
                    /
                    NULLIF(SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))),0)
                ) * 100,
                2
            ) AS ebit_percentage

        FROM pc_analysis_data
        GROUP BY customers
        HAVING total_ebit_cr < 0
        ORDER BY total_ebit_cr ASC
        LIMIT 10;
        """

    # =========================
    # CONTRIBUTION QUERY
    # =========================
    is_contribution_query = (
        ('revenue' in question_lower or 'sales' in question_lower)
        and
        (
                    '%' in question_lower or 'percentage' in question_lower or 'contribution' in question_lower or 'share' in question_lower)
        and
        ('customer' in question_lower or 'customers' in question_lower)
    )

    if is_contribution_query:
        top_n = 20
        match = re.search(r'top\s*(\d+)', question_lower)
        if match:
            top_n = int(match.group(1))

        return f"""
        SELECT 
        ROUND(
            (
                SELECT SUM(customer_sales)
                FROM (
                    SELECT customers,
                    SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) AS customer_sales
                    FROM pc_analysis_data
                    GROUP BY customers
                    ORDER BY customer_sales DESC
                    LIMIT {top_n}
                ) top_customers
            )
            /
            (
                SELECT SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2)))
                FROM pc_analysis_data
            )
            * 100, 2
        ) AS top_{top_n}_revenue_percentage;
        """

    # =========================
    # MOM QUERY
    # =========================
    is_mom_query = (
            (
                    'month over month' in question_lower or
                    'month-over-month' in question_lower or
                    'mom' in question_lower or
                    'monthly growth' in question_lower
            )
            and
            (
                    'revenue' in question_lower or
                    'sales' in question_lower
            )
    )

    if is_mom_query:
        return """
        SELECT 
            month,
            ROUND(
                SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) / 10000000,
                2
            ) AS sales_cr
        FROM pc_analysis_data
        WHERE fy = (SELECT MAX(fy) FROM pc_analysis_data)
        GROUP BY month
        ORDER BY FIELD(
            month,
            'APR','MAY','JUN','JUL','AUG','SEP',
            'OCT','NOV','DEC','JAN','FEB','MAR'
        );
        """
    is_yoy_query = (
            (
                    'year over year' in question_lower or
                    'year-over-year' in question_lower or
                    'yoy' in question_lower
            )
            and
            (
                    'revenue' in question_lower or
                    'sales' in question_lower
            )
    )
    if is_yoy_query:
        return """
        SELECT
            fy,
            ROUND(
                SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) / 10000000,
                2
            ) AS sales_cr
        FROM pc_analysis_data
        GROUP BY fy
        ORDER BY fy;
        """

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": SCHEMA_CONTEXT + history_context
            },
            {
                "role": "user",
                "content": f"""
            Write a valid MySQL SELECT query for this question: {question}

            STRICT RULES:
            1. Return ONLY SQL.
            2. Use SELECT queries only.
            3. Never use INSERT, UPDATE, DELETE, DROP.
            4. Always prefer aggregation when analytical questions are asked.
            5. Use aliases with meaningful names.

            BUSINESS DEFINITIONS:
            - Revenue = sales
            - Profitability = (SUM(ind_ebit) / SUM(sales)) * 100
            - EBIT % = Profitability
            - Margin = EBIT %
            - Budget variance = Actual - Budget
            - Inventory risk = slow_moving + non_moving

            ANALYTICAL QUERY RULES:
            1. Trend Questions
            Examples:
            - monthly trend
            - month over month
            - yoy trend

            → Group by month.

            2. Top/Bottom Questions
            Examples:
            - top 5 customers
            - bottom 10 products

            → Use ORDER BY + LIMIT.

            3. Contribution / Share Questions
            Examples:
            - What percentage of revenue comes from top 20 customers?
            - Revenue contribution of top 10 customers
            - Customer revenue share

            IMPORTANT:
            Use nested SQL.

            Pattern:
            - Aggregate sales by customer
            - Rank by revenue descending
            - Limit top N
            - Sum top N revenue
            - Divide by total revenue
            - Multiply by 100

            4. Profitability Questions
            Examples:
            - high revenue low profitability
            - low margin customers

            Use:
            ROUND(
            (SUM(ind_ebit) / NULLIF(SUM(sales),0)) * 100,
            2
            ) AS ebit_percentage

            5. Comparison Questions
            Examples:
            - budget vs actual
            - compare customers

            Return multiple metrics.

            MONETARY RULES:
            Convert monetary values to Crores:
            SUM(value)/10000000
            Return clean SQL only.
            """
            }
        ],
        temperature=0,      # Must be 0 — deterministic SQL, no creativity
        max_tokens=600
    )

    sql = response.choices[0].message.content.strip()

    # Strip markdown if model wraps in backticks
    if "```" in sql:
        parts = sql.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.upper().startswith("SELECT"):
                sql = cleaned
                break
        else:
            sql = parts[1].strip()
            if sql.lower().startswith("sql"):
                sql = sql[3:].strip()

    # Safety guard — block anything that isn't a SELECT
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError(f"Non-SELECT query blocked: {sql[:100]}")
    # If query calculates a percentage but has no HAVING clause filtering small sales,
    # inject a minimum sales threshold to prevent division anomalies
    sql_upper = sql.upper()


    print("\n===== GENERATED SQL =====")
    print(sql)
    print("=========================\n")
    sql_lower = sql.lower()

    normalized_sql = (
        sql_lower
        .replace(" ", "")
        .replace("\n", "")
        .replace("\t", "")
    )

    monetary_fields = [
        "sales",
        "ind_ebit",
        "ind_va",
        "amount",
        "rm",
        "consumables"
    ]

    comparison_keywords = [
        "case when",
        "current_year",
        "previous_year",
        "change_value",
        "change_cr"
    ]

    return sql

def extract_query_intent(question):
    q = question.lower()

    intent = {
        "primary_metric": None,
        "secondary_metrics": [],
        "analysis_type": None,
        "multi_metric": False
    }
    sales_keywords = ['sales', 'revenue', 'turnover']
    ebit_keywords = ['ebit', 'profitability', 'margin', 'profit']
    inventory_keywords = ['inventory', 'stock']
    ranking_keywords = ['top', 'bottom', 'highest', 'lowest', 'best', 'worst']
    trend_keywords = ['trend', 'growth', 'month over month', 'mom', 'yoy']
    comparison_keywords = ['compare', 'comparison', 'vs', 'versus']
    profit_risk_keywords = ["pulling down profitability", "hurting profits", "profit drainer", "negative ebit", "pulling down profits", "loss making customers"]

    sales_present = any(x in q for x in sales_keywords)
    ebit_present = any(x in q for x in ebit_keywords)
    inventory_present = any(x in q for x in inventory_keywords)

    metrics_found = []
    if sales_present:
        metrics_found.append("sales")
    if ebit_present:
        metrics_found.append("ebit")
    if inventory_present:
        metrics_found.append("inventory")
    if metrics_found:
        intent["primary_metric"] = metrics_found[0]
    if len(metrics_found) > 1:
        intent["secondary_metrics"] = metrics_found[1:]
        intent["multi_metric"] = True
    if any(x in q for x in comparison_keywords):
        intent["analysis_type"] = "comparison"
    elif any(x in q for x in trend_keywords):
        intent["analysis_type"] = "trend"
    elif any(x in q for x in ranking_keywords):
        intent["analysis_type"] = "ranking"
    if any(x in q for x in profit_risk_keywords):
        intent["analysis_type"] = "profit_risk"
    # Important: if multiple metrics explicitly requested, treat as comparison
    if intent["multi_metric"]:
        intent["analysis_type"] = "comparison"
    return intent

def call_openai_response(question: str, sql: str, columns: list, rows: list, conversation_history: list = None, intent=None) -> dict:
    """
    OpenAI Call #2 — Takes SQL result data, returns summary + Chart.js config.
    Uses gpt-4o (better at reasoning and consistent JSON output).
    """
    # ── Unit conversion: monetary columns are stored in Lakhs.
    # We convert to Crores here in Python so GPT never has to do math.
    # IMPORTANT:
    # SQL already returns values in the correct unit.
    # Never perform monetary conversion inside Python.

    converted_columns = columns
    converted_rows = rows

    # Limit data sent to OpenAI to avoid token overflow
    data_preview = json.dumps(converted_rows[:100], indent=2, default=str)

    history_context = ""

    if conversation_history:
        history_context = "\n\nRecent Conversation:\n"

        for msg in conversation_history[-8:]:
            role = msg.get("role", "").upper()
            content = msg.get("content", "")
            history_context += f"{role}: {content}\n"

    intent_context = json.dumps(intent or {}, indent=2)

    prompt = f"""
You are QBER, a business analytics AI for a manufacturing company.
{history_context}

User Question: {question}
Detected Query Intent: {intent_context}
SQL Used: {sql}
Data Retrieved:
Columns: {converted_columns}
Rows: {data_preview}
Total Rows: {len(rows)}

{CHART_RULES}
PRIMARY METRIC & CHART RULES:
1. Use Detected Query Intent to understand what the user wants.
2. If query has primary_metric = sales:
   - chart must primarily visualize sales only
   - do NOT plot EBIT unless explicitly requested
3. If query has primary_metric = ebit:
   - chart must visualize EBIT only
4. If analysis_type = ranking:
   - use bar chart
   - chart should focus on primary metric only
   - avoid multi-metric chart unless user explicitly asks comparison
5. If analysis_type = trend:
   - use line chart
6. If analysis_type = comparison:
   - multiple datasets allowed
   
Secondary metrics may be mentioned in summary.
If intent.multi_metric = true:
- include multiple datasets in chart
- dual metric charts are allowed

Examples:
sales + ebit → bar + bar OR bar + line
sales + margin → bar + line
Examples:
- "top 10 customers by sales" → chart sales only
- "top products by EBIT" → chart EBIT only
- "compare sales and EBIT of top customers" → chart both
- "monthly revenue trend" → sales line chart only
VERY IMPORTANT:

CRITICAL SUMMARY RULES:
1. Use ONLY numbers present in the rows.
2. Never generate a number not found in the data.
3. Do not invent calculations.
   You MAY calculate:
    - Difference between values already present
    - Growth %
    - Variance %
    - Contribution %
    - Share %
   ONLY when both source values are present in the dataset.
4. Never extrapolate.
5. Never explain WHY something happened.
6. Never state business reasons or assumptions.
7. If the rows contain 10 records, discuss only those records.
8. If a value is already in Crores, use it exactly as provided.

PROFITABILITY RISK RULE:
For queries like:
- customers pulling down profitability
- customers hurting profits
- worst profit contributors
- biggest profit drainers

Do NOT rank by EBIT percentage alone.
Reason: EBIT percentage becomes misleading when sales are very small.
Instead:
1. Calculate total EBIT
2. Filter negative EBIT
3. Rank by total EBIT ascending (most negative first)
Only use EBIT % as supporting metric.

If the dataset contains columns such as:
current_year
previous_year
change
growth
variance

you MUST discuss the comparison.
Do not ignore comparison columns.

Always mention:
- current value
- previous value
- increase/decrease
Respond with ONLY a valid JSON object — no markdown, no backticks, no preamble.

Example:

Input row:
{{
  "customers":"MONDELEZ",
  "total_sales_cr":9.31
}}

Valid:
₹9.31 Cr

Invalid:
₹931 Cr
₹9310 Cr
₹9,31,000 Cr

Never scale, multiply, divide, convert, round, or reinterpret any numeric value. Use values exactly as provided.
9. If data has 1 row and 1 numeric column → summary must be 1-2 lines only.
10. Never add business interpretation like:
   - "strategic planning"
   - "important for growth"
   - "critical insight"
11. Be factual only.
Format:
{{
  "summary": "Write a factual summary using ONLY values that appear in the provided rows.
    Rules:
    - Every number mentioned must exist in the dataset.
    - Never invent values.
    - Never estimate values.
    - Never calculate additional metrics.
    - Never infer causes.
    - Never speculate.
    - Never mention any number not present in the rows.
    - If data is ranked, describe the ranking.
    - If data is a trend, describe the trend.
    - If data contains only one row, simply state the value.
    - Keep summary between 3 and 5 sentences.
     Sound like a senior business analyst, not a robot.",
  "chart": {{
    "type": "bar",
    "title": "Chart title here",
    "labels": ["label1", "label2", "label3"],
    "datasets": [
      {{
        "label": "Dataset label",
        "data": [value1, value2, value3]
      }}
    ]
  }}
}}

If chart is not appropriate, set "chart": null.
For multi-metric charts (e.g. sales vs ebit), include multiple objects in datasets array.
MONETARY CHART SCALING RULE:
- All monetary values are already in Crores (₹ Cr). Use them exactly as given — no division needed.
- Label all monetary datasets as "(₹ Cr)".
- When stating counts always use the exact row count from data provided — never estimate.

EXECUTIVE INSIGHT RULES:
When comparison columns exist:
- identify highest increase
- identify largest decline
- identify top contributor
- identify lowest performer
Use only values present in the data. Do not speculate on causes. Do not invent explanations.
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": """
                    You are a business reporting engine.
                
                    Return valid JSON only.
                
                    Never invent values.
                    Never infer causes.
                    Never speculate.
                    Only use values present in supplied data.
                    """
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        max_tokens=1200
    )

    raw = response.choices[0].message.content.strip()

    # Clean up if model still wraps in markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)

def build_yoy_chart_response(rows):
    labels = []
    sales = []
    growth = []
    prev_sales = None
    for row in rows:
        fy = str(row.get("fy"))
        sales_cr = float(row.get("sales_cr", 0))
        labels.append(fy)
        sales.append(round(sales_cr, 2))
        if prev_sales is None or prev_sales == 0:
            growth.append(None)
        else:
            yoy = ((sales_cr - prev_sales) / prev_sales) * 100
            growth.append(round(yoy, 2))

        prev_sales = sales_cr
    valid_growth = [g for g in growth if g is not None]

    if len(valid_growth) == 1:
        summary = (
            f"Revenue increased from ₹{sales[0]} Cr to ₹{sales[-1]} Cr. "
            f"Year-over-year growth was {valid_growth[0]}%."
        )
    else:
        highest_growth = max(valid_growth) if valid_growth else 0
        lowest_growth = min(valid_growth) if valid_growth else 0

        summary = (
            f"Revenue trend shows yearly fluctuations. Sales started at ₹{sales[0]} Cr "
            f"and ended at ₹{sales[-1]} Cr. Highest YoY growth was {highest_growth}% "
            f"while the sharpest decline was {lowest_growth}%."
        )

    return {
        "summary": summary,
        "chart": {
            "type": "combo",
            "title": "YEAR-OVER-YEAR REVENUE GROWTH TREND",
            "labels": labels,
            "datasets": [
                {
                    "label": "Sales (₹ Cr)",
                    "data": sales,
                    "type": "bar",
                    "yAxisID": "y"
                },
                {
                    "label": "YoY Growth %",
                    "data": growth,
                    "type": "line",
                    "yAxisID": "y1"
                }
            ]
        }
    }

def build_mom_chart_response(rows):
    labels = [r['month'] for r in rows]
    sales = [float(r['sales_cr']) for r in rows]
    growth = [None]

    for i in range(1, len(sales)):
        prev = sales[i - 1]
        curr = sales[i]

        if prev == 0:
            growth.append(None)
        else:
            pct = round(((curr - prev) / prev) * 100, 2)
            growth.append(pct)
    max_growth = max([g for g in growth[1:] if g is not None])
    min_growth = min([g for g in growth[1:] if g is not None])
    summary = (
        f"Revenue trend shows fluctuations across the fiscal year. "
        f"Sales started at ₹{sales[0]} Cr in {labels[0]} and ended at ₹{sales[-1]} Cr in {labels[-1]}. "
        f"Highest MoM growth was {max_growth}% while the sharpest decline was {min_growth}%."
    )
    return {
        "summary": summary,
        "chart": {
            "type": "combo",
            "title": "Month-over-Month Revenue Growth Trend",
            "labels": labels,
            "datasets": [
                {
                    "type": "bar",
                    "label": "Sales (₹ Cr)",
                    "data": sales,
                    "yAxisID": "y"
                },
                {
                    "type": "line",
                    "label": "MoM Growth %",
                    "data": growth,
                    "yAxisID": "y1"
                }
            ]
        }
    }
