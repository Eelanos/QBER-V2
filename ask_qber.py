# ask_qber.py
import os
from dotenv import load_dotenv

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

        sql = None

        try:
            sql = call_openai_sql(question, conversation_history)
            print(f"[Ask QBER] SQL Generated: {sql}")

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

            result = call_openai_response(question, columns, rows)

            return jsonify({
                "summary":   result.get("summary", ""),
                "chart":     result.get("chart", None),
                "sql_used":  sql,
                "row_count": len(rows)
            })

        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        except json.JSONDecodeError:
            return jsonify({"error": "AI returned unexpected format. Please try again."}), 500


        except Exception as e:

            print(f"[Ask QBER] Error: {e}")

            # Check if it's a database/SQL execution error

            error_str = str(e).lower()

            if any(x in error_str for x in ['unknown column', 'doesn\'t exist', 'no such table',

                                            'operationalerror', 'table', 'column', 'field list']):
                return jsonify({

                    "error": "Your database does not have this information.",

                    "sql_used": sql or "SQL not generated"

                }), 400

            return jsonify({

                "error": f"Something went wrong: {str(e)}",

                "sql_used": sql or "SQL not generated"

            }), 500

# ─── Schema Context for OpenAI ────────────────────────────────────────────────
SCHEMA_CONTEXT = """
You are a MySQL expert working with a business analytics portal called QBER.
The data belongs to a manufacturing/packaging company.

You have access to THREE tables in the database. Pick the right table based on the question.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLE 1: pc_analysis_data  — main P&L / sales / cost data
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIMENSION COLUMNS (plain text, no casting needed):
- year              : Calendar year e.g. "2023"
- fy                : Financial year e.g. "FY24", "FY25"
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
RULES THAT APPLY TO ALL THREE TABLES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ALL numeric columns across all tables are VARCHAR with commas (e.g. "1,23,456.78").
   ALWAYS use: CAST(REPLACE(column_name, ',', '') AS DECIMAL(18,2))
   for ANY numeric operation — SUM, AVG, comparison, arithmetic, everything.
2. Only write SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or ALTER.
3. Always use GROUP BY when using aggregate functions.
4. Default ORDER BY the most relevant metric DESC.
5. Limit to 20 rows maximum unless user asks for more.
6. Return ONLY the raw SQL query — no explanation, no markdown, no backticks.
7. ALWAYS backtick `30_to_60` and `60_to_90` when querying stock_ageing.

TABLE SELECTION GUIDE — pick the right table:
- Questions about sales, revenue, EBIT, margins, costs, customers, products → pc_analysis_data
- Questions about closing stock, inventory value, inventory days, non-moving/slow-moving stock → closing_stock
- Questions about stock age, how long stock has been sitting, ageing buckets, above-90-day stock → stock_ageing

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
2. ALWAYS add this HAVING clause when calculating any % metric to filter bad data:
   HAVING SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) > 1000000
   (This filters out customers/products with less than ₹10L sales — removes anomalies)
3. ALWAYS use ROUND(..., 2) on percentage results
4. When user asks for EBIT%, always show both the EBIT% AND total sales together
   so the user can judge the result in context
   
- RM + Consumables          = rm + consumables (both cast first)
- Dead stock risk %         = non_moving / amount * 100  (closing_stock)
- Ageing risk %             = above_90 / amount * 100    (stock_ageing)

EXAMPLE QUERIES:

-- Sales & EBIT by product
SELECT products,
       SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) AS total_sales,
       SUM(CAST(REPLACE(ind_ebit, ',', '') AS DECIMAL(18,2))) AS total_ebit
FROM pc_analysis_data
GROUP BY products
ORDER BY total_ebit DESC
LIMIT 10;

-- Closing stock value and inventory days by plant
SELECT plant,
       SUM(CAST(REPLACE(amount, ',', '') AS DECIMAL(18,2))) AS total_stock_value,
       AVG(CAST(REPLACE(inventory_days, ',', '') AS DECIMAL(18,2))) AS avg_inventory_days
FROM closing_stock
GROUP BY plant
ORDER BY total_stock_value DESC;

-- Stock ageing breakdown by BU (note backticks on digit-start columns)
SELECT bu,
       SUM(CAST(REPLACE(amount, ',', '') AS DECIMAL(18,2))) AS total_amount,
       SUM(CAST(REPLACE(below_30, ',', '') AS DECIMAL(18,2))) AS aged_below_30,
       SUM(CAST(REPLACE(`30_to_60`, ',', '') AS DECIMAL(18,2))) AS aged_30_to_60,
       SUM(CAST(REPLACE(`60_to_90`, ',', '') AS DECIMAL(18,2))) AS aged_60_to_90,
       SUM(CAST(REPLACE(above_90, ',', '') AS DECIMAL(18,2))) AS aged_above_90
FROM stock_ageing
GROUP BY bu
ORDER BY aged_above_90 DESC;
"""

CHART_RULES = """
Choose chart type based on the data:
- Comparing named categories (products, customers, segments, plants) → "bar"
- Trend over time (monthly, yearly sequence) → "line"
- Cost breakdown / composition / share → "doughnut"
- Top N ranking → "bar" (horizontal feel, still use bar type)
- Single number result or 1 row → set chart to null, summary only

Set chart to null if: only 1 data point, or question is purely yes/no or factual.
"""

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

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": SCHEMA_CONTEXT + history_context
            },
            {
                "role": "user",
                "content": f"Write a MySQL SELECT query to answer: {question}"
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
    if ('/' in sql and 'SALES' in sql_upper and 'HAVING' not in sql_upper
                and 'WHERE' in sql_upper):
        sql = sql.rstrip().rstrip(';')
        sql += "\nHAVING SUM(CAST(REPLACE(sales, ',', '') AS DECIMAL(18,2))) > 1000000"

    return sql


def call_openai_response(question: str, columns: list, rows: list) -> dict:
    """
    OpenAI Call #2 — Takes SQL result data, returns summary + Chart.js config.
    Uses gpt-4o (better at reasoning and consistent JSON output).
    """
    # Limit data sent to OpenAI to avoid token overflow
    data_preview = json.dumps(rows[:20], indent=2, default=str)

    prompt = f"""
You are QBER, a business analytics AI for a manufacturing company.

The user asked: "{question}"

Data retrieved from database:
Columns: {columns}
Rows (max 20 shown): {data_preview}
Total rows returned: {len(rows)}

{CHART_RULES}

Respond with ONLY a valid JSON object — no markdown, no backticks, no preamble.

Format:
{{
  "summary": "3-5 sentence plain English business insight. Be specific — use actual numbers from the data. Use ₹ for currency. Convert large numbers to Lakhs (L) or Crores (Cr) for readability. Sound like a senior business analyst, not a robot.",
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
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are QBER, a precise business analytics AI. Always respond with valid raw JSON only. No markdown. No backticks."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3,
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
