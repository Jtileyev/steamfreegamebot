# AI Agent MCP Servers Usage Guide

## 1. Codacy (`mcp_codacy_codacy`) — Code Quality Analysis

### When to Use:
- **Before committing code** — run quality analysis to catch issues early
- **During code review** — analyze pull requests for problems
- **When refactoring** — identify technical debt and code smells
- **For security audits** — find vulnerabilities and compliance issues

### Key Tools:
| Tool | Purpose |
|------|---------|
| `codacy_setup_repository` | Initialize Codacy for a new repository |
| `codacy_get_issue` | Get details about a specific code issue |
| `codacy_get_file_coverage` | Check test coverage for a file |
| `codacy_list_repository_pull_requests` | List and analyze PRs |
| `codacy_get_pattern` | Get definition of a code pattern/rule |

### Example Scenarios:
```
User: "Check code quality of this file"
→ Use code quality analysis tools

User: "What issues does Codacy find in my PR?"
→ Use activate_pull_request_management_tools, then list/analyze PRs

User: "Find duplicate code in my project"
→ Use activate_code_duplication_and_analysis_tools
```

---

## 2. Context7 (`mcp_io_github_ups`) — Library Documentation

### When to Use:
- **Learning a new library** — get up-to-date documentation
- **Checking API usage** — find correct method signatures and examples
- **Troubleshooting** — find solutions in official docs
- **Before implementing features** — understand best practices

### Key Tools:
| Tool | Purpose |
|------|---------|
| `resolve-library-id` | Find the correct library ID by name |
| `get-library-docs` | Fetch documentation for a specific topic |

### Workflow:
1. **Always call `resolve-library-id` first** to get the correct library ID
2. Then call `get-library-docs` with the resolved ID and topic

### Example Scenarios:
```
User: "How do I use React hooks?"
→ resolve-library-id("react") → get-library-docs(id, topic="hooks")

User: "Show me Laravel authentication docs"
→ resolve-library-id("laravel") → get-library-docs(id, topic="authentication")

User: "How to connect to MySQL with PHP PDO?"
→ resolve-library-id("php") → get-library-docs(id, topic="PDO MySQL")
```

### Parameters for `get-library-docs`:
- `mode='code'` — for API references and code examples (default)
- `mode='info'` — for conceptual guides and architecture explanations
- `page` — use pagination (1-10) if more context needed

---

## 3. Memory/Knowledge Graph (`mcp_memory`) — Persistent Knowledge

### When to Use:
- **Storing user preferences** — remember settings across sessions
- **Tracking project context** — store architecture decisions, conventions
- **Building relationships** — connect concepts, files, features
- **Long-term memory** — remember important facts about the project

### Key Tools:
| Tool | Purpose |
|------|---------|
| `read_graph` | Read entire knowledge graph |
| `search_nodes` | Search for specific information |
| `open_nodes` | Retrieve specific nodes by name |
| `create_relations` | Create relationships between entities |

### Activation Required:
- `activate_observation_management_tools` — for adding/deleting observations
- `activate_entity_management_tools` — for creating/deleting entities
- `activate_node_access_tools` — for searching and opening nodes

### Example Scenarios:
```
User: "Remember that this project uses PSR-4 autoloading"
→ Create entity for project, add observation about PSR-4

User: "What do you know about this codebase?"
→ read_graph or search_nodes

User: "Link the User model to the authentication system"
→ create_relations between User and Auth entities
```

---

## 4. Playwright Browser (`mcp_microsoft_pla`) — Web Automation

### When to Use:
- **Testing web applications** — automated UI testing
- **Web scraping** — extract data from websites
- **Form automation** — fill and submit forms
- **Visual verification** — take screenshots for comparison
- **Debugging web issues** — inspect network requests, console errors

### Key Tools:
| Tool | Purpose |
|------|---------|
| `browser_snapshot` | Get accessibility snapshot (preferred over screenshot) |
| `browser_click` | Click on elements |
| `browser_type` | Type text into inputs |
| `browser_navigate` | Go to a URL |
| `browser_network_requests` | View all network requests |
| `browser_console_messages` | Get console logs/errors |
| `browser_tabs` | Manage browser tabs |
| `browser_wait_for` | Wait for text/element/time |

### Activation Required:
- `activate_browser_navigation_tools` — for navigation, clicks, keyboard
- `activate_form_and_file_management_tools` — for forms and file uploads
- `activate_page_capture_tools` — for screenshots and snapshots

### Workflow:
1. Navigate to URL with `browser_navigate` (activate navigation tools first)
2. Take snapshot with `browser_snapshot` to see page structure
3. Interact using `ref` attributes from snapshot
4. Verify results with another snapshot or assertions

### Example Scenarios:
```
User: "Test the login form on my website"
→ Navigate → snapshot → fill form → click submit → verify

User: "Check if there are any JavaScript errors on the page"
→ browser_console_messages(onlyErrors=true)

User: "Download this file from the website"
→ Navigate → click download link → handle file
```

---

## 5. Serena (`mcp_oraios_serena`) — Intelligent Code Analysis

### When to Use:
- **Understanding large codebases** — get symbol overviews without reading entire files
- **Precise code editing** — modify specific functions/classes
- **Finding references** — locate all usages of a symbol
- **Refactoring** — rename symbols, update references
- **Code navigation** — find files, patterns, symbols efficiently

### Key Activation Tools:
| Activation Tool | Provides |
|-----------------|----------|
| `activate_file_search_and_listing_tools` | find_file, list_dir, search_for_pattern |
| `activate_symbol_management_tools` | find_symbol, get_symbols_overview, rename, replace |
| `activate_code_insertion_tools` | insert_before_symbol, insert_after_symbol |
| `activate_memory_management_tools` | Project memory files |
| `activate_task_adherence_tools` | Focus and completion checking |

### Direct Tools:
| Tool | Purpose |
|------|---------|
| `activate_project` | Switch active project |
| `get_current_config` | View current configuration |

### Best Practices:
1. **Don't read entire files** — use `get_symbols_overview` first
2. **Use symbol tools** — `find_symbol` with `include_body=False` to explore
3. **Read selectively** — only `include_body=True` when you need the code
4. **Find references** — use `find_referencing_symbols` before modifying

### Example Scenarios:
```
User: "What classes are in this file?"
→ activate_symbol_management_tools → get_symbols_overview

User: "Find all usages of the User class"
→ find_referencing_symbols for User

User: "Add a new method to the PaymentService class"
→ find_symbol(PaymentService) → insert_after_symbol or replace_symbol_body
```

---

## 6. Sequential Thinking (`mcp_sequentialthi`) — Complex Problem Solving

### When to Use:
- **Complex multi-step problems** — break down into manageable thoughts
- **Planning and design** — work through architecture decisions
- **Debugging difficult issues** — systematic analysis with backtracking
- **When scope is unclear** — explore and adjust approach dynamically

### Key Features:
- Adjust `totalThoughts` as you progress
- Mark revisions with `isRevision` and `revisesThought`
- Branch thinking with `branchFromThought` and `branchId`
- Express uncertainty and explore alternatives

### Parameters:
| Parameter | Purpose |
|-----------|---------|
| `thought` | Current thinking step |
| `thoughtNumber` | Current position in sequence |
| `totalThoughts` | Estimated total (adjustable) |
| `nextThoughtNeeded` | Continue thinking? |
| `isRevision` | Revising previous thought? |
| `needsMoreThoughts` | Need to extend beyond estimate? |

### Example Scenarios:
```
User: "Design a payment system for my application"
→ Use sequential thinking to:
  1. Analyze requirements
  2. Consider payment providers
  3. Design database schema
  4. Plan API endpoints
  5. Consider security
  6. Revise if needed

User: "Debug why users can't log in"
→ Use sequential thinking to:
  1. Identify possible causes
  2. Check authentication flow
  3. Examine session handling
  4. Test hypotheses
  5. Branch if multiple issues found
```

---

## Quick Reference: When to Use What

| User Need | Primary Tool |
|-----------|--------------|
| "Check code quality" | Codacy |
| "How do I use [library]?" | Context7 |
| "Remember this for later" | Memory |
| "Test my website" | Playwright |
| "Find where X is used" | Serena |
| "Help me think through this" | Sequential Thinking |
| "Analyze this PR" | Codacy |
| "Get React documentation" | Context7 |
| "What do you know about my project?" | Memory |
| "Fill out this form automatically" | Playwright |
| "Refactor this class" | Serena |
| "Design a complex feature" | Sequential Thinking |

---

## Combining Tools Effectively

### Example: Full Feature Implementation
1. **Context7** — Get documentation for relevant libraries
2. **Sequential Thinking** — Plan the implementation approach
3. **Serena** — Find related code, understand structure
4. **Memory** — Store decisions and context
5. **Codacy** — Verify code quality before commit
6. **Playwright** — Test the feature in browser

### Example: Code Review Workflow
1. **Codacy** — Get automated analysis of PR
2. **Serena** — Deep dive into specific changes
3. **Context7** — Verify library usage is correct
4. **Sequential Thinking** — Analyze complex logic changes
