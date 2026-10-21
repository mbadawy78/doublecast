# Discovery and auto mode

Doublecast protects names in two ways that need no typing:

1. **Auto mode** (always on) finds names in any text from its structure and remembers them.
2. **Discovery** (`doublecast discover`) reads your company's systems once, classifies every
   column, and protects everything they contain, refreshed as often as you like.

Lists you type yourself (`terms:`) become optional: use them for a handful of crown jewels.

## Auto mode: no lists, no AI model

| Where the name is | Example | Remembered? |
|---|---|---|
| Email headers | `From: Theodora Vlachaki <t.v@...>` | yes |
| Greetings | `Dear Petros,` · `Αγαπητέ κ. Ανδρέου,` · `Hallo Herr Weber,` | yes |
| Titles | `Ms Vlachaki` · `κα Παπαδοπούλου` · `Frau Weber` · `M. Dupont` | yes |
| Sign-offs | `Kind regards,` / `Με εκτίμηση,` followed by a name line | yes |
| Company legal forms | `Brennwald Handel GmbH` · `Μαρινάκης Διανομές ΑΕ` · `Nordia S.A.` | yes, and the bare name too |
| Spreadsheet columns | a column headed Customer / Πελάτης / Salesperson / Είδος / Αποθήκη | yes |
| Capitalised names mid-sentence | `we met Georgia Konstantinou` | no (broad net) |
| First + last name at a sentence start | `Theodora Vlachaki will confirm` (common first names) | no |
| Greek article + capitalised word | `μίλησα με τον Παπαδόπουλο` | no |

"Remembered" means the name is caught everywhere afterwards, in any case or Greek inflection,
even where nothing gives it away. Learned names are stored encrypted in
`~/.doublecast/<workspace>.rules`.

Because a remembered value is swapped *everywhere*, learning is strict. It never keeps:

- ordinary words in any of the six languages ("Dear Reader", "Thanks, Operations",
  "Net Weight KG", "Marketing Ltd"), job titles ("Mr President", "Herr Direktor") or
  department names;
- lone first names ("Dear Maria" swaps Maria there, but does not learn her);
- short codes and single ordinary words from spreadsheet cells ("THE", "ALFA", "Discount").

If something was learned that should not have been: `doublecast discover ignore "Value"`, or
`doublecast discover forget learned` to start over (a running proxy picks this up and does
not re-add the old names).

Code is not prose: fenced code blocks, inline `code` and shell/import lines are not searched
for names (secrets and keys in them are still redacted).

The broad net leaves ordinary vocabulary alone ("Annual Leave Policy", "Πρόγραμμα
Εκπαίδευσης") using offline word-frequency lists for all six languages. Turn the net off with
`auto.capitalized_phrases: false` if you prefer fewer swaps over wider coverage.

**Measured.** On 130 realistic documents written blind by someone else
([benchmark-blind.md](benchmark-blind.md)), auto mode alone lets about one name in five
through: lone first names, nicknames, lower-case names in chats. With the names from a
master-data export added (what discovery does), none of those names leaked. On the project's
own generated emails ([benchmark-auto.md](benchmark-auto.md)) structured situations leak 0%.

## Discovery

```bash
doublecast discover path ~/Documents/masterdata   # no config needed: a folder of Excel/CSV files
doublecast discover                               # every source configured under discover:
doublecast discover --dry-run                     # show what would be protected, save nothing
doublecast discover status                        # what is protected, from where, refreshed when
doublecast discover ignore "Value"                # never protect this value
doublecast discover forget SOURCE|learned         # drop a source's rules, or everything learned
```

### What it does

1. Connects to each source (read-only).
2. Lists tables and columns.
3. Samples each column (200 rows by default) and classifies it from **the column name** (in six
   languages, read together with the table name, e.g. `Customers[Name]`) and **the values**
   (emails, IBAN and VAT checksums, phone shapes, people's names, company legal forms, codes).
4. For sensitive columns, reads the distinct values and turns them into rules.
5. Shows you the result (examples masked) and asks before saving.

Columns it deliberately does **not** turn into rules: geography fields (City, Country,
Region, postcode, also inside an address such as `AddressCity`), classifications (Customer
Group, Store Type, Store Format, Category), general-ledger accounts and cost centres
(`MainAccountName`), descriptions on invoice and order lines, short codes without digits
(company code `ALFA`), dates and amounts (amounts are covered by money scaling), placeholder
values ("Total", "Λοιποί", "N/A"), and single ordinary words ("Croissant", "Discount"), which
would otherwise be swapped everywhere. Street addresses *are* protected.

### Sources

```yaml
discover:
  sample_rows: 200
  max_values_per_column: 50000
  sources:
    - type: folder
      path: ~/Documents/masterdata
    - type: m365
      contacts: true
      mail_messages: 1000          # names and addresses only; never bodies or attachments
      sharepoint_sites: [Sales, Purchasing]
      sharepoint_files: 50         # Excel/CSV files per site, downloaded to a temp folder and deleted
    - type: powerbi
      workspaces: [Commercial]     # omit to scan every dataset you can read
      # tables: [Customer, Product] # only if your tenant refuses COLUMNSTATISTICS()
    - type: d365fo
      url: https://yourcompany.operations.dynamics.com
      # entities: [CustomersV3, VendorsV2, ReleasedProductsV2]
    - type: dataverse
      url: https://yourorg.crm4.dynamics.com
    - type: businesscentral
      environment: production
    - type: sql
      url: mssql+pyodbc://reader@server/erp?driver=ODBC+Driver+18+for+SQL+Server
```

| Source | Reads | Needs |
|---|---|---|
| `folder` | every sheet of every .xlsx/.xlsm/.csv | nothing |
| `sql` | every table/view (or `tables:`) | `pip install "doublecast[sql]"` + the database driver; a read-only login |
| `m365` | Outlook contacts; names/addresses of people you email; SharePoint lists and spreadsheets | Microsoft sign-in (below); Graph permissions `Contacts.Read`, `Mail.ReadBasic`, `Sites.Read.All` |
| `powerbi` | dimension tables of semantic models | Microsoft sign-in; `Dataset.Read.All`, `Workspace.Read.All`; tenant setting **Dataset Execute Queries REST API** on; Read + Build on the dataset |
| `d365fo` | customers, vendors, released products, contacts, workers, warehouses (all companies) | Microsoft sign-in; the app registered in F&O under *Microsoft Entra applications* |
| `dataverse` | accounts, contacts, users, products, leads, competitors | Microsoft sign-in; *Access Dynamics 365 as organization users* |
| `businesscentral` | customers, vendors, items, employees, contacts per company | Microsoft sign-in; Business Central API permission |

Entity names that do not exist in your version are skipped and listed in the report.

**Power BI note:** the Execute Queries API does not allow INFO functions or DMVs, so
Doublecast lists tables with the DAX function `COLUMNSTATISTICS()`. This has been tested
against simulated responses, not yet against every tenant configuration. If your tenant
refuses it, the report says so; list the tables with `tables:`.

### Microsoft sign-in

Microsoft requires every tool to have its own app registration; there is no shared one a
public tool may use. Your IT admin creates it once in **Microsoft Entra ID → App
registrations → New registration**:

1. Name: `Doublecast` (single tenant).
2. **Authentication → Advanced settings → Allow public client flows: Yes** (device sign-in).
3. **API permissions → Add**, delegated, only what you will use:
   - Microsoft Graph: `User.Read`, `Contacts.Read`, `Mail.ReadBasic`, `Sites.Read.All`
   - Power BI Service: `Dataset.Read.All`, `Workspace.Read.All`
   - Dynamics ERP: *Access Dynamics AX data* (F&O also needs the client ID added under
     System administration → Setup → Microsoft Entra applications)
   - Dynamics CRM: *user_impersonation* (Dataverse)
   - Dynamics 365 Business Central: *user_impersonation*
4. Grant admin consent if your tenant requires it.

Then in `~/.doublecast/config.yaml`:

```yaml
microsoft:
  tenant_id: yourcompany.onmicrosoft.com
  client_id: 00000000-0000-0000-0000-000000000000
```

The first `doublecast discover` prints a short code: open https://microsoft.com/devicelogin,
enter it, and sign in as yourself. Doublecast reads only what *your* account can already see.
Tokens are cached encrypted with the vault key.

```bash
pip install "doublecast[m365]"
```

### Keeping it fresh

Run discovery on a schedule so new customers and staff are protected the day they appear:

```bash
doublecast discover --yes --quiet
```

- **macOS / Linux** (cron, every night at 02:00): `0 2 * * * /path/to/doublecast discover --yes --quiet`
- **Windows** (Task Scheduler): a daily task running `doublecast discover --yes --quiet`

Microsoft sources need one interactive sign-in first; after that the cached token is
refreshed silently. If Microsoft ever asks for a fresh sign-in (password change, policy, about
90 days of inactivity; this varies by tenant), a scheduled run does not wait for it: it skips
that source, reports "Microsoft sign-in needed", and keeps the rules it already had. Run
`doublecast discover` once in a terminal to sign in again.

Long scans are throttle-safe: HTTP 429 and 5xx answers and network timeouts are retried with
back-off (honouring `Retry-After`), and tokens are renewed during the scan.

### Privacy of discovery itself

- Sources are only read; nothing is written back.
- Nothing read is sent anywhere: classification runs locally, with no AI service involved.
- The resulting rules contain your master data, so they are encrypted at rest
  (`~/.doublecast/<workspace>.rules`, permissions 600).
- SharePoint spreadsheets are downloaded to a temporary folder and deleted after the scan.
- Mail access uses `Mail.ReadBasic`: sender and recipient names and addresses only.
