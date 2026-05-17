# Nutribox Admin Guide: Managing Menus & Pricing

Welcome to the Nutribox Menu Management guide! The new system provides a streamlined, centralized interface to manage your meal tiers, dynamic pricing, weekly menu graphics, and plan availability—all without needing to create hundreds of duplicate plan records.

You can access the Menu Management page from your Admin dashboard.

---

## 1. Tab 1: Tier Settings & Pricing

Tiers (e.g., "Protein Rich", "Classic") are the **single source of truth** for your meal offerings. Instead of managing individual plans, you manage Tiers and apply Pricing Rules over time.

### Adding a New Tier
1. Click the **Add New Tier** button.
2. Enter the **Tier Name** (e.g., "Keto Menu"). The system will auto-generate the URL slug.
3. Select the **Diet Support**: 
   - *Veg & Non-Veg* (supports both diets)
   - *Veg Only* (e.g., for Fruits Bowl)
   - *Non-Veg Only*
4. Set default **Delivery Charges** (per week and per month).
5. Toggle **Active** and save.

### Managing Pricing History
Every tier uses a "Pricing History" engine. This allows you to schedule new price increases or discounts ahead of time without affecting old data.
1. Click the green **Manage Pricing** (money bill) icon on any tier row.
2. Under "Add New Price Rule", select the Diet (Veg/Non-Veg), enter the new **Price / Meal**, and pick the **Effective Date**.
3. **Important**: You cannot backdate a price rule. All new rules must be scheduled for today or the future.
4. Old prices are automatically superseded when a new price reaches its Effective Date.

### Reordering & Toggling
- **Reordering**: Use the grab handle on the left of any tier row to drag it up or down. The order here dictates how tiers appear to customers.
- **Deactivating**: Toggle the switch on a tier row to disable the entire tier globally.

---

## 2. Tab 2: Weekly Images

Instead of typing out dishes, Nutribox uses a high-quality visual approach. Here you upload weekly menu graphics per tier and diet.

### The Coverage Grid
On the right side of the screen, you will see the **Week Coverage** grid. 
- It lists every active Tier + Diet combination.
- **Green border**: Image successfully uploaded for this week.
- **Yellow placeholder**: Image is missing for this week.

### Uploading a Menu Graphic
1. Select the **Week Starting** Monday date using the calendar.
2. Click heavily on a missing cell in the Coverage Grid. It will auto-fill the forms on the left.
3. (Optional) If you have a single menu graphic that applies to both Veg and Non-Veg for a specific tier, select **"Both"** in the Diet Type dropdown. The system will automatically use this single image as a fallback for both diets.
4. Drop your image (PNG, JPG, WEBP) into the upload zone.
5. Click **Publish**.

### Copying from Last Week
To save time, simply click **Copy from Last Week**. The system will duplicate all active menu images from the previous week into your currently selected week.

---

## 3. Tab 3: Plan Matrix

This tab tells the system *which* combinations of Meals, Slots, and Durations are actually visible and available for customers to buy. 

*Note: You do not set prices here. Prices are automatically calculated dynamically from Tab 1 (Price/Meal × Meal Count + Delivery).*

### Managing Availability
You will see a large grid for every tier:
- **Columns**: Show the Duration (Weekly/Monthly) and the Slot (Breakfast/Dinner/Both).
- **Rows**: Show the Diet (Veg/Non-Veg).

1. Find the exact combination you want to offer (e.g., Veg + Weekly + Breakfast).
2. Look at the calculated price to ensure it is correct. Hover over the price to see the exact math tooltip (e.g., `₹95 × 6 meals + ₹10 delivery`).
3. **Toggle the switch** to make that specific combination available or unavailable.
4. Use the **Enable all** or **Disable all** buttons next to a Tier's name to bulk modify the grid instantly.

---

## FAQ & Best Practices

**Q: Do I need to create a new plan for every new week?**
A: **No.** The Plan Matrix (Tab 3) determines what customers can buy, and those stay active indefinitely. Every week, you solely need to upload the visual menu images in Tab 2.

**Q: Why can't I set Non-Veg pricing for the "Fruits Bowl" tier?**
A: The system restricts diet pricing layers based on the Tier's root `Diet Support` settings. If a Tier is set to "Veg Only", it rejects non-veg pricing or non-veg images to prevent errors.

**Q: If a customer chooses a monthly plan, what image do they see?**
A: The user will always see the current week's image based on today's date. When Monday rolls over, the image on their dashboard will automatically update to the newest graphic you published in Tab 2.
