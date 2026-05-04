# code-outline-graph: Real Examples

## React Component

Instead of reading `EmployeesPage.js` (200+ lines):
```
list_outline({"file": "frontend/src/pages/EmployeesPage.js"})
→ [{name: "EmployeesPage", kind: "function", start: 12, end: 198},
   {name: "useEffect", kind: "method", start: 25, end: 40}, ...]

read_symbol_body({"name": "EmployeesPage", "file": "frontend/src/pages/EmployeesPage.js"})
→ only the component body
```

## Finding a Bug

```
resolve_edit_target({"description": "shift assignment validation logic"})
→ [{name: "validateShift", file: "backend/services/shift.js", start: 45, end: 67}]

read_symbol_body({"name": "validateShift", "file": "backend/services/shift.js"})
→ 22 lines, not 300
```

## Adding a Feature

```
find_by_keyword({"query": "roster"})
→ lists all roster-related symbols across entire codebase

get_symbol({"name": "RosterService"})
→ {file: "...", start: 1, end: 120, signature: "class RosterService"}

read_symbol_body({"name": "RosterService", "file": "..."})
→ only that class
```

## Checking Imports Before Editing

```
get_file_header({"file": "frontend/src/pages/DashboardPage.js"})
→ import React from 'react';
  import { useState, useEffect } from 'react';
  import AppLayout from '../components/layout/AppLayout';
  ...
```
