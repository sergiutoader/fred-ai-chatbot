# Fred Design Quick Reference

## 🎯 Most Common Customizations

### 1. Change Logo

**Files to modify:**
- `/frontend/public/images/your-logo.svg` - Add your logo here
- `/frontend/index.html` line 5 - Update favicon
- `/frontend/src/app/SideBar.tsx` line 191 - Update default logo name

```typescript
// SideBar.tsx line 191
const logoName = getProperty("logoName") || "your-logo";
```

```html
<!-- index.html line 5 -->
<link id="favicon" rel="icon" type="image/svg" href="/images/your-logo.svg" />
```

---

### 2. Change Primary Brand Color

**File:** `/frontend/src/styles/theme.tsx`

**Lines to modify:**
- Line 140 (light theme primary)
- Line 194 (dark theme primary)

```typescript
// Light theme (line 140)
primary: { 
  main: "#YOUR_COLOR",      // Your brand color
  light: "#LIGHTER_SHADE",  // Lighter version
  dark: "#DARKER_SHADE",    // Darker version
  contrastText: "#fff"      // Text on primary color
}

// Dark theme (line 194)
primary: { 
  main: "#YOUR_COLOR_LIGHTER",  // Lighter for dark backgrounds
  light: "#LIGHTER_SHADE",
  dark: "#DARKER_SHADE",
  contrastText: "#fff"
}
```

---

### 3. Change Background Colors

**File:** `/frontend/src/styles/theme.tsx`

**Hero Gradient (lines 126-130):**
```typescript
const lightHeroFrom = "#YOUR_LIGHT_COLOR";
const lightHeroTo = "#YOUR_LIGHT_COLOR";

const darkHeroFrom = "#YOUR_DARK_COLOR";
const darkHeroTo = "#YOUR_DARK_COLOR";
```

**Main Backgrounds (lines 135-138, 189-192):**
```typescript
// Light theme
background: {
  default: "#ffffff",   // Page background
  paper: "#f4f4f4",     // Card background
}

// Dark theme
background: {
  default: "#1b1b1b",   // Page background
  paper: "#333333",     // Card background
}
```

---

### 4. Change Sidebar Colors

**File:** `/frontend/src/styles/theme.tsx`

**Lines 176 (light) and 229 (dark):**

```typescript
// Light theme (line 176)
sidebar: { 
  background: "#fafafaf2",    // Sidebar background
  activeItem: "#f0f0f5cc",    // Active menu highlight
  hoverColor: "#00000008"     // Hover effect
}

// Dark theme (line 229)
sidebar: { 
  background: "#121214f2",    // Sidebar background
  activeItem: "#42424db3",    // Active menu highlight
  hoverColor: "#ffffff0d"     // Hover effect
}
```

---

## 📍 File Locations Map

```
fred/
├── frontend/
│   ├── index.html                          # Favicon, page title
│   ├── public/
│   │   └── images/
│   │       ├── fred.svg                    # Default logo
│   │       └── favicon.svg                 # Browser tab icon
│   └── src/
│       ├── styles/
│       │   └── theme.tsx                   # 🎨 MAIN THEME FILE
│       ├── app/
│       │   ├── App.tsx                     # Logo/title loading
│       │   ├── SideBar.tsx                 # Sidebar with logo
│       │   └── LayoutWithSidebar.tsx       # Layout structure
│       └── utils/
│           └── image.tsx                   # Image loading utilities
```

---

## 🎨 Color Properties Quick Reference

| Property | Location | Affects |
|----------|----------|---------|
| `primary.main` | Lines 140, 194 | Buttons, active items, links |
| `heroBackgroundGrad` | Lines 126-130 | Page backgrounds, cards |
| `sidebar.background` | Lines 176, 229 | Sidebar background |
| `sidebar.activeItem` | Lines 176, 229 | Selected menu item |
| `background.default` | Lines 135, 189 | Main page background |
| `background.paper` | Lines 138, 192 | Container backgrounds |
| `text.primary` | Lines 174, 228 | Main text color |
| `surfaces.soft` | Lines 180, 233 | Paper, drawer backgrounds |
| `surfaces.raised` | Lines 182, 235 | Card backgrounds |

---

## 🚀 Quick Start Workflow

### Step 1: Prepare Your Assets
```bash
# Create your logo as SVG (recommended size: 36x36px to 48x48px)
# Save as: /frontend/public/images/my-logo.svg
```

### Step 2: Update Logo References
```bash
# Edit these files:
# 1. /frontend/index.html (line 5)
# 2. /frontend/src/app/SideBar.tsx (line 191)
```

### Step 3: Choose Your Colors
```bash
# Use a color picker to get hex values
# Primary color: #XXXXXX
# Light shade: #XXXXXX
# Dark shade: #XXXXXX
```

### Step 4: Update Theme
```bash
# Edit: /frontend/src/styles/theme.tsx
# Update lines: 126-130 (gradients), 140 (light primary), 194 (dark primary)
```

### Step 5: Test
```bash
cd frontend
make run
# Open http://localhost:5173
# Toggle dark/light mode to test both themes
```

---

## 🎯 Pre-Made Color Schemes

### Corporate Blue
```typescript
// Primary
primary: { main: "#0066cc", light: "#3399ff", dark: "#003d7a" }

// Gradients
lightHeroFrom = "#e6f2ff"
lightHeroTo = "#cce5ff"
darkHeroFrom = "#001a33"
darkHeroTo = "#003366"

// Sidebar
sidebar: { background: "#e6f2fff2", activeItem: "#cce5ffcc", hoverColor: "#0066cc08" }
```

### Modern Green
```typescript
// Primary
primary: { main: "#00c853", light: "#5efc82", dark: "#009624" }

// Gradients
lightHeroFrom = "#e8f5e9"
lightHeroTo = "#c8e6c9"
darkHeroFrom = "#1b5e20"
darkHeroTo = "#2e7d32"

// Sidebar
sidebar: { background: "#e8f5e9f2", activeItem: "#c8e6c9cc", hoverColor: "#00c85308" }
```

### Elegant Purple
```typescript
// Primary
primary: { main: "#7c4dff", light: "#b47cff", dark: "#3f1dcb" }

// Gradients
lightHeroFrom = "#ede7f6"
lightHeroTo = "#d1c4e9"
darkHeroFrom = "#1a0033"
darkHeroTo = "#311b92"

// Sidebar
sidebar: { background: "#1a0033f2", activeItem: "#311b92b3", hoverColor: "#7c4dff0d" }
```

### Warm Orange
```typescript
// Primary
primary: { main: "#ff6f00", light: "#ffa040", dark: "#c43e00" }

// Gradients
lightHeroFrom = "#fff3e0"
lightHeroTo = "#ffe0b2"
darkHeroFrom = "#3e2723"
darkHeroTo = "#5d4037"

// Sidebar
sidebar: { background: "#fff3e0f2", activeItem: "#ffe0b2cc", hoverColor: "#ff6f0008" }
```

---

## 🔧 Common Adjustments

### Make Sidebar Wider/Narrower
**File:** `/frontend/src/styles/theme.tsx` lines 294-295

```typescript
layout: {
  sidebarWidth: 250,           // Change from 200
  sidebarCollapsedWidth: 80,   // Keep as is
}
```

### Change Font
**File:** `/frontend/src/styles/theme.tsx` line 241

```typescript
fontFamily: "Your Font, sans-serif",
```

Don't forget to import the font in `/frontend/index.html`:
```html
<link href="https://fonts.googleapis.com/css2?family=Your+Font:wght@300;400;500;600&display=swap" rel="stylesheet">
```

### Adjust Border Radius (Roundness)
**File:** `/frontend/src/styles/theme.tsx`

```typescript
// Cards (line 378)
borderRadius: 16,  // Change to 8 for less round, 24 for more round

// Sidebar menu items (line 284, 320)
borderRadius: "8px",  // Change to "4px" or "12px"
```

---

## 📋 Testing Checklist

- [ ] Logo appears in sidebar (top-left)
- [ ] Favicon shows in browser tab
- [ ] Light mode colors look good
- [ ] Dark mode colors look good
- [ ] Text is readable on all backgrounds
- [ ] Active menu items are clearly visible
- [ ] Hover effects work properly
- [ ] Primary color appears on buttons
- [ ] Cards and dialogs have correct colors
- [ ] Theme toggle works correctly

---

## 🆘 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Logo not showing | Check file path and extension match |
| Colors not updating | Clear cache (Cmd+Shift+R) and restart dev server |
| Text hard to read | Adjust contrast between text and background colors |
| Sidebar looks wrong | Check both `sidebar.background` and `sidebar.activeItem` |
| Changes not visible | Ensure you're editing the correct theme (light/dark) |

---

## 💡 Pro Tips

1. **Use color picker tools** to extract colors from your brand guidelines
2. **Test with real content** - colors may look different with actual text/images
3. **Check accessibility** - ensure sufficient contrast (use WebAIM contrast checker)
4. **Keep it simple** - start with primary color, then expand gradually
5. **Document your changes** - add comments in theme.tsx for future reference
6. **Version control** - commit working states before major changes

---

## 🔗 Useful Links

- **Material-UI Color Tool:** https://m2.material.io/resources/color/
- **Contrast Checker:** https://webaim.org/resources/contrastchecker/
- **Color Palette Generator:** https://coolors.co/
- **Fred Documentation:** https://fredk8.dev

---

**For detailed explanations, see:** `DESIGN_CUSTOMIZATION_GUIDE.md`
