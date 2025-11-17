# Fred Frontend Design Architecture

## 🏗️ Component Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                         App.tsx                              │
│  - Loads frontend config from backend                        │
│  - Sets document title and favicon dynamically               │
│  - Wraps everything in theme providers                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  ThemeProvider                               │
│  - Applies light or dark theme from theme.tsx               │
│  - Switches based on ApplicationContext.darkMode            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│               LayoutWithSidebar.tsx                          │
│  ┌──────────────┬─────────────────────────────────────────┐ │
│  │              │                                         │ │
│  │   SideBar    │         Main Content Area              │ │
│  │              │         (Outlet)                       │ │
│  │   - Logo     │                                         │ │
│  │   - Menu     │   ┌─────────────────────────────────┐  │ │
│  │   - Theme    │   │  Chat Page                      │  │ │
│  │     Toggle   │   │  Knowledge Page                 │  │ │
│  │              │   │  Monitoring Pages               │  │ │
│  │              │   │  Agent Hub                      │  │ │
│  │              │   │  Account Page                   │  │ │
│  │              │   └─────────────────────────────────┘  │ │
│  │              │                                         │ │
│  └──────────────┴─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎨 Theme Application Flow

```
theme.tsx
    │
    ├─── lightPalette ──────┐
    │    - primary colors    │
    │    - backgrounds       │
    │    - text colors       │
    │    - sidebar colors    │
    │    - chart colors      │
    │    - surfaces          │
    │                        │
    └─── darkPalette ───────┤
         - primary colors    │
         - backgrounds       │
         - text colors       │
         - sidebar colors    │
         - chart colors      │
         - surfaces          │
                             │
                             ▼
                    createTheme()
                             │
                             ├─── Typography
                             ├─── Layout (sidebar widths)
                             └─── Component Overrides
                                  │
                                  ├─── MuiTooltip
                                  ├─── MuiTypography
                                  ├─── MuiDialog
                                  ├─── MuiPaper
                                  ├─── MuiCard
                                  ├─── MuiDrawer
                                  └─── MuiAppBar
                                       │
                                       ▼
                              Applied to all components
```

---

## 🖼️ Logo Loading Flow

```
Backend Config
    │
    ├─── logoName: "fred"
    └─── siteDisplayName: "Fred"
         │
         ▼
    App.tsx (lines 29-39)
         │
         ├─── Sets document.title
         └─── Updates favicon href
              │
              ▼
    SideBar.tsx (line 191)
         │
         └─── getProperty("logoName") || "fred"
              │
              ▼
    ImageComponent (utils/image.tsx)
         │
         └─── Loads /images/{logoName}.svg
              │
              ├─── Success: Display logo
              └─── Error: Fallback to default
```

---

## 🎨 Color Inheritance Map

```
Hero Gradient Colors
    │
    ├─── lightHeroFrom/To ──────┐
    └─── darkHeroFrom/To ────────┤
                                 │
                                 ▼
                          surfaces.soft
                          surfaces.raised
                                 │
                                 ├─── MuiPaper
                                 ├─── MuiCard
                                 ├─── MuiDrawer
                                 └─── MuiAppBar

Primary Colors
    │
    ├─── primary.main ──────────┐
    ├─── primary.light          │
    └─── primary.dark           │
                                │
                                ├─── Active menu items
                                ├─── Buttons
                                ├─── Links
                                └─── Focus states

Sidebar Colors
    │
    ├─── sidebar.background ────┐
    ├─── sidebar.activeItem     │
    └─── sidebar.hoverColor     │
                                │
                                └─── SideBar component

Background Colors
    │
    ├─── background.default ────┐
    └─── background.paper       │
                                │
                                ├─── Page backgrounds
                                └─── Container backgrounds

Text Colors
    │
    ├─── text.primary ──────────┐
    ├─── text.secondary         │
    └─── text.disabled          │
                                │
                                └─── All text elements
```

---

## 📐 Layout Structure

```
┌─────────────────────────────────────────────────────────────┐
│  Browser Window (100vh)                                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  LayoutWithSidebar (display: flex, height: 100vh)      │ │
│  │  ┌──────────────┬──────────────────────────────────┐  │ │
│  │  │              │                                   │  │ │
│  │  │  SideBar     │  Main Content                    │  │ │
│  │  │              │  (flex: 1)                       │  │ │
│  │  │  200px wide  │  ┌────────────────────────────┐  │  │ │
│  │  │  (or 80px    │  │                            │  │  │ │
│  │  │   collapsed) │  │  Scrollable Content        │  │  │ │
│  │  │              │  │  (overflowY: auto)         │  │  │ │
│  │  │  ┌────────┐  │  │                            │  │  │ │
│  │  │  │ Logo   │  │  │  - Chat interface          │  │  │ │
│  │  │  └────────┘  │  │  - Knowledge base          │  │  │ │
│  │  │              │  │  - Monitoring dashboards   │  │  │ │
│  │  │  ┌────────┐  │  │  - Agent hub               │  │  │ │
│  │  │  │ Toggle │  │  │  - Account settings        │  │  │ │
│  │  │  └────────┘  │  │                            │  │  │ │
│  │  │              │  │                            │  │  │ │
│  │  │  Menu Items  │  │                            │  │  │ │
│  │  │  - Chat      │  │                            │  │  │ │
│  │  │  - Monitor   │  │                            │  │  │ │
│  │  │  - Knowledge │  │                            │  │  │ │
│  │  │  - Agent     │  │                            │  │  │ │
│  │  │  - Account   │  │                            │  │  │ │
│  │  │              │  │                            │  │  │ │
│  │  │  ┌────────┐  │  │                            │  │  │ │
│  │  │  │ Theme  │  │  │                            │  │  │ │
│  │  │  │ Toggle │  │  │                            │  │  │ │
│  │  │  └────────┘  │  └────────────────────────────┘  │  │ │
│  │  │              │                                   │  │ │
│  │  └──────────────┴──────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Sidebar Component Breakdown

```
SideBar.tsx
    │
    ├─── Header Section (lines 215-245)
    │    │
    │    └─── Logo Container
    │         ├─── Avatar (42x42px)
    │         └─── ImageComponent (36x36px)
    │              └─── Loads /images/{logoName}.svg
    │
    ├─── Toggle Button (lines 247-261)
    │    └─── Collapse/Expand sidebar
    │
    ├─── Menu Items (lines 263-403)
    │    │
    │    ├─── Chat
    │    ├─── Monitoring (with submenu)
    │    │    ├─── KPI
    │    │    ├─── Runtime
    │    │    └─── Logs
    │    ├─── Knowledge
    │    ├─── Agent
    │    └─── Account
    │
    └─── Footer Section (lines 405-463)
         │
         ├─── Theme Toggle
         └─── Website Link
```

---

## 🎨 Theme Color Application

### Light Theme
```
Page Background: #ffffff (background.default)
    │
    └─── Sidebar: #fafafaf2 (sidebar.background)
         │
         ├─── Active Item: #f0f0f5cc (sidebar.activeItem)
         │    └─── Text: #4F83CC (primary.main)
         │
         └─── Hover: #00000008 (sidebar.hoverColor)

Content Area: #ffffff (background.default)
    │
    ├─── Cards: linear-gradient(#ffffffcc, #f7f7f7f2) (surfaces.raised)
    │
    └─── Papers: linear-gradient(#ffffffff, #ffffffff) (surfaces.soft)
```

### Dark Theme
```
Page Background: #1b1b1b (background.default)
    │
    └─── Sidebar: #121214f2 (sidebar.background)
         │
         ├─── Active Item: #42424db3 (sidebar.activeItem)
         │    └─── Text: #6482AD (primary.main)
         │
         └─── Hover: #ffffff0d (sidebar.hoverColor)

Content Area: #1b1b1b (background.default)
    │
    ├─── Cards: linear-gradient(#1f2230cc, #1b1f2ae6) (surfaces.raised)
    │
    └─── Papers: linear-gradient(#191923ff, #191923ff) (surfaces.soft)
```

---

## 🔄 State Management Flow

```
ApplicationContext
    │
    ├─── darkMode (boolean)
    │    │
    │    └─── Controls theme selection
    │         │
    │         ├─── true → darkTheme
    │         └─── false → lightTheme
    │
    ├─── isSidebarCollapsed (boolean)
    │    │
    │    └─── Controls sidebar width
    │         │
    │         ├─── true → 80px
    │         └─── false → 200px
    │
    └─── toggleDarkMode()
         toggleSidebar()
```

---

## 📦 Component Style Override Hierarchy

```
MUI Default Styles
    │
    ▼
theme.tsx Component Overrides
    │
    ├─── MuiTooltip
    │    └─── Uses surfaces.raised + custom styling
    │
    ├─── MuiPaper
    │    └─── Uses surfaces.soft + border
    │
    ├─── MuiCard
    │    └─── Uses surfaces.raised + border + borderRadius
    │
    ├─── MuiDrawer
    │    └─── Uses surfaces.soft + borderRight
    │
    └─── MuiAppBar
         └─── Uses surfaces.soft + backdropFilter + borderBottom
              │
              ▼
    Component-Specific sx Props
              │
              └─── Inline styles in components
```

---

## 🎨 Visual Design Tokens

### Spacing Scale
```
Sidebar padding:
- Expanded: px: 2 (16px)
- Collapsed: px: 1 (8px)

Menu items:
- Height: 44px
- Margin bottom: 0.8 (6.4px)
- Border radius: 8px

Logo:
- Avatar: 42x42px
- Image: 36x36px
```

### Typography Scale
```
Base font size: 12px
Font family: Inter, sans-serif

Hierarchy:
- h1: 2rem (24px), weight 600
- h2: 1.5rem (18px), weight 500
- body1: 1rem (12px), weight 400
- body2: 0.875rem (10.5px), weight 400
- sidebar: 14px, weight 300
```

### Border Radius Scale
```
- Cards: 16px
- Dialogs: 16px
- Menu items: 8px
- Buttons: varies by component
```

### Shadow Scale
```
Light mode:
- Cards: 0 6px 16px rgba(0,0,0,0.12)
- Tooltips: 0 6px 16px rgba(0,0,0,0.12)

Dark mode:
- Cards: 0 8px 24px rgba(0,0,0,0.35)
- Tooltips: 0 8px 24px rgba(0,0,0,0.35)
```

---

## 🔍 File Dependencies

```
index.html
    │
    └─── Loads index.tsx
         │
         └─── Loads App.tsx
              │
              ├─── Imports theme.tsx
              │    │
              │    ├─── lightTheme
              │    └─── darkTheme
              │
              ├─── Imports ApplicationContextProvider
              │    │
              │    └─── Provides darkMode state
              │
              └─── Imports LayoutWithSidebar
                   │
                   └─── Imports SideBar
                        │
                        └─── Imports ImageComponent
                             │
                             └─── Loads from /public/images/
```

---

## 🎯 Customization Impact Matrix

| Change | Files Affected | Components Updated | Rebuild Required |
|--------|---------------|-------------------|------------------|
| Logo | `public/images/`, `index.html`, `SideBar.tsx` | Sidebar, Favicon | No (hot reload) |
| Primary Color | `theme.tsx` | All buttons, active states, links | No (hot reload) |
| Background | `theme.tsx` | All pages, cards, papers | No (hot reload) |
| Sidebar Colors | `theme.tsx` | Sidebar only | No (hot reload) |
| Typography | `theme.tsx` | All text elements | No (hot reload) |
| Layout Widths | `theme.tsx` | Sidebar, content area | No (hot reload) |
| Component Styles | `theme.tsx` | Specific MUI components | No (hot reload) |

---

## 💡 Design System Best Practices

### Color Consistency
```
✅ DO:
- Use theme.palette.primary.main for primary actions
- Use theme.palette.surfaces.* for backgrounds
- Use theme.palette.text.* for text
- Keep semantic colors (error, warning, success) standard

❌ DON'T:
- Hardcode hex colors in components
- Mix light/dark theme colors
- Use primary color for errors
- Ignore contrast ratios
```

### Component Styling
```
✅ DO:
- Use sx prop for component-specific styles
- Reference theme tokens
- Keep styles close to components
- Use theme.spacing() for consistent spacing

❌ DON'T:
- Use inline styles with hardcoded values
- Override MUI defaults without theme
- Create custom CSS files for MUI components
- Use !important
```

### Responsive Design
```
✅ DO:
- Use theme.breakpoints for media queries
- Test on mobile, tablet, desktop
- Collapse sidebar on small screens
- Use flexible layouts

❌ DON'T:
- Hardcode pixel breakpoints
- Assume desktop-only usage
- Ignore touch interactions
- Use fixed widths
```

---

**For implementation details, see:**
- `DESIGN_CUSTOMIZATION_GUIDE.md` - Complete customization guide
- `QUICK_DESIGN_REFERENCE.md` - Quick reference for common changes
