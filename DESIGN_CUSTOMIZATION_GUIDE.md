# Fred Frontend Design Customization Guide

This guide explains how to customize the Fred chat interface design, including logos, colors, and visual elements.

## Project Overview

**Fred** is a production-ready agentic AI platform with:
- **Python agentic backend** (FastAPI + LangGraph)
- **Python knowledge flow backend** (FastAPI) for document ingestion and vector search
- **React frontend** (TypeScript + Vite + Material-UI)

The frontend is a modern chat interface with dark/light theme support, built using Material-UI (MUI) components.

---

## 🎨 Design System Architecture

### Key Files for Customization

| File | Purpose | What You Can Change |
|------|---------|-------------------|
| `/frontend/src/styles/theme.tsx` | **Main theme configuration** | Colors, gradients, typography, component styles |
| `/frontend/public/images/` | **Logo and icon storage** | Replace logo files here |
| `/frontend/index.html` | **HTML entry point** | Favicon reference, page title |
| `/frontend/src/app/SideBar.tsx` | **Sidebar component** | Logo display, menu items |
| `/frontend/src/app/App.tsx` | **App configuration** | Dynamic logo and title loading |

---

## 🖼️ Logo Customization

### Where Logos Are Used

1. **Browser Favicon** (tab icon)
2. **Sidebar Logo** (top-left corner)
3. **Dynamic Logo** (configurable via backend)

### How to Update the Logo

#### Option 1: Replace the Default Logo File

1. **Create your logo as SVG** (recommended for scalability)
   - Name it `fred.svg` or choose a custom name
   - Recommended size: 36x36px to 48x48px

2. **Place it in the public images folder:**
   ```
   /frontend/public/images/your-logo.svg
   ```

3. **Update references:**

   **For Favicon** - Edit `/frontend/index.html`:
   ```html
   <link id="favicon" rel="icon" type="image/svg" href="/images/your-logo.svg" />
   ```

   **For Sidebar** - The logo is dynamically loaded from backend config, but defaults to "fred"
   
   Edit `/frontend/src/app/SideBar.tsx` line 191 to change the default:
   ```typescript
   const logoName = getProperty("logoName") || "your-logo";
   ```

#### Option 2: Configure Logo via Backend

The logo can be dynamically configured through the backend API response:
- The frontend fetches `logoName` from the backend config
- This allows changing logos without rebuilding the frontend

**Backend configuration location:**
```
/agentic-backend/config/configuration.yaml
```

Add or modify:
```yaml
frontend_settings:
  properties:
    logoName: "your-logo"
    siteDisplayName: "Your App Name"
```

### Logo Display Specifications

**Sidebar Logo:**
- Location: `/frontend/src/app/SideBar.tsx` lines 235-243
- Container: 42x42px Avatar component
- Image size: 36x36px
- Background: Transparent
- Format: SVG preferred (PNG also supported)

**Code reference:**
```typescript
<Avatar
  sx={{
    width: 42,
    height: 42,
    backgroundColor: "transparent",
  }}
>
  <ImageComponent name={logoName} width="36px" height="36px" />
</Avatar>
```

---

## 🎨 Color Customization

### Theme Structure

Fred uses **Material-UI theming** with separate light and dark palettes defined in `/frontend/src/styles/theme.tsx`.

### Color Categories

#### 1. **Hero Gradient Colors** (Lines 126-130)

These define the main background gradient:

```typescript
// Light theme
const lightHeroFrom = "#ffffffff";  // White
const lightHeroTo = "#ffffffff";    // White

// Dark theme
const darkHeroFrom = "#191923ff";   // Dark blue-grey
const darkHeroTo = "#191923ff";     // Dark blue-grey
```

**Impact:** Background of Paper, Card, Drawer, and AppBar components

---

#### 2. **Primary Colors** (Lines 140, 194)

Main brand color used for buttons, active states, and accents:

```typescript
// Light theme
primary: { 
  main: "#4F83CC",      // Blue
  light: "#879ed9",     // Light blue
  dark: "#023D54",      // Dark blue
  contrastText: "#fff"  // White text
}

// Dark theme
primary: { 
  main: "#6482AD",      // Lighter blue
  light: "#879ed9",     // Light blue
  dark: "#404040",      // Dark grey
  contrastText: "#fff"  // White text
}
```

**Impact:**
- Active sidebar items
- Button backgrounds
- Link colors
- Active state indicators
- Primary action buttons

---

#### 3. **Background Colors** (Lines 135-138, 189-192)

```typescript
// Light theme
background: {
  default: "#ffffff",   // Main background
  paper: "#f4f4f4",     // Card/paper background
}

// Dark theme
background: {
  default: "#1b1b1b",   // Main background
  paper: "#333333",     // Card/paper background
}
```

**Impact:** Overall page background and container backgrounds

---

#### 4. **Sidebar Colors** (Lines 176, 229)

```typescript
// Light theme
sidebar: { 
  background: "#fafafaf2",    // Sidebar background
  activeItem: "#f0f0f5cc",    // Active menu item
  hoverColor: "#00000008"     // Hover effect
}

// Dark theme
sidebar: { 
  background: "#121214f2",    // Sidebar background
  activeItem: "#42424db3",    // Active menu item
  hoverColor: "#ffffff0d"     // Hover effect
}
```

**Impact:** 
- Sidebar background color
- Active menu item highlighting
- Hover effects on menu items

---

#### 5. **Text Colors** (Lines 174, 228)

```typescript
// Light theme
text: { 
  primary: "#000",      // Main text
  secondary: "#000",    // Secondary text
  disabled: "#BDBDBD"   // Disabled text
}

// Dark theme
text: { 
  primary: "#fff",      // Main text
  secondary: "#bbb",    // Secondary text
  disabled: "#888888"   // Disabled text
}
```

**Impact:** All text throughout the application

---

#### 6. **Chart Colors** (Lines 146-173, 200-227)

Used for data visualizations and charts:

```typescript
chart: {
  primary: "#08519c",       // Primary chart color
  secondary: "#3182bd",     // Secondary chart color
  green: "#4caf50",         // Success/positive
  blue: "#1976d2",          // Information
  red: "#ef5350",           // Error/negative
  orange: "#ffbb00",        // Warning
  purple: "#9c27b0",        // Accent
  yellow: "#ffd149",        // Highlight
  // ... gradient scales for intensity levels
}
```

**Impact:** Charts, graphs, and data visualizations

---

#### 7. **Semantic Colors** (Lines 142-145, 196-199)

Status and feedback colors:

```typescript
// Light theme
info: { main: "#6986D0", ... }      // Information messages
warning: { main: "#ffbb00", ... }   // Warning messages
error: { main: "#d32f2f", ... }     // Error messages
success: { main: "#2e7d32", ... }   // Success messages

// Dark theme (adjusted for dark backgrounds)
info: { main: "#81d4fa", ... }
warning: { main: "#ffcc80", ... }
error: { main: "#e57373", ... }
success: { main: "#81c784", ... }
```

**Impact:** 
- Alert messages
- Toast notifications
- Status indicators
- Validation feedback

---

#### 8. **Surface Colors** (Lines 180-183, 233-236)

Derived from hero gradient for consistent layering:

```typescript
// Light theme
surfaces: {
  soft: `linear-gradient(180deg, ${lightHeroFrom}, ${lightHeroTo})`,
  raised: `linear-gradient(180deg, #ffffffcc, #f7f7f7f2)`,
}

// Dark theme
surfaces: {
  soft: `linear-gradient(180deg, ${darkHeroFrom}, ${darkHeroTo})`,
  raised: `linear-gradient(180deg, #1f2230cc, #1b1f2ae6)`,
}
```

**Impact:**
- MuiPaper components (dialogs, menus)
- MuiCard components (content cards)
- MuiDrawer components (side panels)
- MuiAppBar components (top bars)

---

### How to Change Colors

#### Step 1: Edit the Theme File

Open `/frontend/src/styles/theme.tsx`

#### Step 2: Modify Color Values

**Example: Change primary brand color to purple**

```typescript
// Find line 140 (light theme) and 194 (dark theme)

// Light theme
primary: { 
  main: "#9c27b0",      // Purple instead of blue
  light: "#ba68c8",     // Light purple
  dark: "#7b1fa2",      // Dark purple
  contrastText: "#fff"
}

// Dark theme
primary: { 
  main: "#ce93d8",      // Lighter purple for dark mode
  light: "#f3e5f5",     // Very light purple
  dark: "#7b1fa2",      // Dark purple
  contrastText: "#000"  // Black text for light purple
}
```

#### Step 3: Update Hero Gradient (Optional)

For a more dramatic change, update the hero gradient:

```typescript
// Lines 126-130
const lightHeroFrom = "#f3e5f5";  // Light purple
const lightHeroTo = "#e1bee7";    // Slightly darker purple

const darkHeroFrom = "#4a148c";   // Deep purple
const darkHeroTo = "#6a1b9a";     // Purple
```

#### Step 4: Adjust Sidebar Colors

```typescript
// Light theme (line 176)
sidebar: { 
  background: "#f3e5f5f2",    // Light purple tint
  activeItem: "#e1bee7cc",    // Purple active state
  hoverColor: "#9c27b008"     // Purple hover
}

// Dark theme (line 229)
sidebar: { 
  background: "#1a0033f2",    // Very dark purple
  activeItem: "#4a148cb3",    // Deep purple active
  hoverColor: "#ce93d80d"     // Purple hover
}
```

---

## 🎯 Quick Customization Recipes

### Recipe 1: Corporate Blue Theme

```typescript
// Primary colors
primary: { main: "#0066cc", light: "#3399ff", dark: "#003d7a" }

// Hero gradient
const lightHeroFrom = "#e6f2ff";
const lightHeroTo = "#cce5ff";
const darkHeroFrom = "#001a33";
const darkHeroTo = "#003366";

// Sidebar
sidebar: { 
  background: "#e6f2fff2", 
  activeItem: "#cce5ffcc", 
  hoverColor: "#0066cc08" 
}
```

### Recipe 2: Modern Green Theme

```typescript
// Primary colors
primary: { main: "#00c853", light: "#5efc82", dark: "#009624" }

// Hero gradient
const lightHeroFrom = "#e8f5e9";
const lightHeroTo = "#c8e6c9";
const darkHeroFrom = "#1b5e20";
const darkHeroTo = "#2e7d32";

// Sidebar
sidebar: { 
  background: "#e8f5e9f2", 
  activeItem: "#c8e6c9cc", 
  hoverColor: "#00c85308" 
}
```

### Recipe 3: Elegant Dark Purple Theme

```typescript
// Primary colors
primary: { main: "#7c4dff", light: "#b47cff", dark: "#3f1dcb" }

// Hero gradient
const lightHeroFrom = "#ede7f6";
const lightHeroTo = "#d1c4e9";
const darkHeroFrom = "#1a0033";
const darkHeroTo = "#311b92";

// Sidebar
sidebar: { 
  background: "#1a0033f2", 
  activeItem: "#311b92b3", 
  hoverColor: "#7c4dff0d" 
}
```

---

## 🔧 Component-Specific Styling

### Sidebar Customization

**File:** `/frontend/src/app/SideBar.tsx`

**Key styling areas:**

1. **Sidebar width** (lines 294-295 in theme.tsx):
```typescript
layout: {
  sidebarWidth: 200,           // Expanded width
  sidebarCollapsedWidth: 80,   // Collapsed width
}
```

2. **Menu item height** (line 286, 322):
```typescript
height: 44,  // Change to adjust menu item size
```

3. **Border radius** (line 284, 320):
```typescript
borderRadius: "8px",  // Rounded corners for menu items
```

### Card and Paper Components

**Configured in theme.tsx lines 365-400 (light) and 479-513 (dark)**

```typescript
MuiCard: {
  styleOverrides: {
    root: ({ theme }) => ({
      background: theme.palette.surfaces.raised,
      border: `1px solid ${theme.palette.divider}`,
      borderRadius: 16,  // Change for more/less rounding
    }),
  },
}
```

### Typography

**Font family** (line 241):
```typescript
fontFamily: "Inter, sans-serif",  // Change to your preferred font
```

**Font sizes** (lines 242-263):
```typescript
fontSize: 12,  // Base font size
h1: { fontSize: "2rem", fontWeight: 600 },
h2: { fontSize: "1.5rem", fontWeight: 500 },
body1: { fontSize: "1rem", fontWeight: 400 },
```

---

## 🚀 Testing Your Changes

### Development Mode

1. **Start the frontend dev server:**
   ```bash
   cd frontend
   make run
   ```

2. **Open browser:**
   ```
   http://localhost:5173
   ```

3. **Hot reload:** Changes to theme.tsx will automatically reload

### Theme Toggle

- Use the theme toggle button in the sidebar (bottom section)
- Test both light and dark modes
- Ensure sufficient contrast for accessibility

---

## 📋 Checklist for Complete Redesign

- [ ] Replace logo file in `/frontend/public/images/`
- [ ] Update favicon in `/frontend/index.html`
- [ ] Update default logo name in `SideBar.tsx`
- [ ] Modify primary colors in `theme.tsx`
- [ ] Adjust hero gradient colors
- [ ] Update sidebar colors
- [ ] Customize background colors
- [ ] Test light mode appearance
- [ ] Test dark mode appearance
- [ ] Verify text contrast (accessibility)
- [ ] Check all semantic colors (error, warning, success)
- [ ] Review chart colors if using visualizations
- [ ] Test on different screen sizes
- [ ] Update site title in backend config

---

## 🎨 Color Impact Reference

| Color Property | Affects |
|----------------|---------|
| `primary.main` | Active menu items, buttons, links, focus states |
| `heroBackgroundGrad` | Main page backgrounds, cards, dialogs |
| `sidebar.background` | Sidebar background |
| `sidebar.activeItem` | Selected menu item background |
| `sidebar.hoverColor` | Menu item hover effect |
| `background.default` | Main page background |
| `background.paper` | Card and container backgrounds |
| `text.primary` | Main text color |
| `text.secondary` | Secondary text, labels |
| `surfaces.soft` | Paper, Drawer, AppBar backgrounds |
| `surfaces.raised` | Card, elevated component backgrounds |

---

## 💡 Best Practices

1. **Maintain Contrast:** Ensure text is readable on all backgrounds (WCAG AA minimum)
2. **Test Both Themes:** Always check light and dark modes
3. **Use Semantic Colors:** Keep error red, success green, warning yellow for UX consistency
4. **Gradual Changes:** Start with primary color, then expand to other elements
5. **Version Control:** Commit working states before major changes
6. **Document Custom Colors:** Add comments in theme.tsx for custom color choices

---

## 🔍 Advanced Customization

### Adding Custom Color Tokens

Edit the type augmentation (lines 26-84 in theme.tsx):

```typescript
interface Palette {
  // Add your custom color
  myCustomColor: {
    main: string;
    light: string;
    dark: string;
  };
}

interface PaletteOptions {
  myCustomColor?: Partial<Palette["myCustomColor"]>;
}
```

Then add to palette definitions:

```typescript
const lightPalette = {
  // ... existing colors
  myCustomColor: {
    main: "#ff5722",
    light: "#ff8a65",
    dark: "#e64a19",
  },
};
```

### Custom Component Overrides

Add to the `components` section in theme creation:

```typescript
components: {
  MuiButton: {
    styleOverrides: {
      root: {
        borderRadius: 20,  // Pill-shaped buttons
        textTransform: 'none',  // No uppercase
      },
    },
  },
}
```

---

## 📚 Additional Resources

- **Material-UI Theme Documentation:** https://mui.com/material-ui/customization/theming/
- **Color Palette Generator:** https://m2.material.io/design/color/the-color-system.html
- **Accessibility Checker:** https://webaim.org/resources/contrastchecker/
- **Fred Project Site:** https://fredk8.dev

---

## 🆘 Troubleshooting

### Changes Not Appearing

1. Clear browser cache (Cmd+Shift+R / Ctrl+Shift+F5)
2. Restart the dev server
3. Check browser console for errors

### Colors Look Wrong

1. Verify hex color format includes `#`
2. Check alpha channel (last 2 digits for transparency)
3. Ensure both light and dark themes are updated

### Logo Not Showing

1. Verify file exists in `/frontend/public/images/`
2. Check file extension matches (`.svg` vs `.png`)
3. Verify logoName matches filename (without extension)
4. Check browser console for 404 errors

---

**Last Updated:** 2025
**Fred Version:** Latest
**Maintainer:** Thales Group
