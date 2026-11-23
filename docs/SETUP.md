# Setup and deployment

1. Create a **private** GitHub repository named `MTGRetailSaleTracker`.
2. Unzip the package, open a terminal in the extracted folder, and initialize Git:
   ```bash
   git init
   git add .
   git commit -m "Initial governed MTG retailer tracker foundation"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/MTGRetailSaleTracker.git
   git push -u origin main
   ```
3. GitHub Actions runs unit tests and creates a **preview** artifact. It does not collect stores or promotions.
4. Run local quick-start commands in README. Do not import `examples/` into production.
5. Before production, configure authorized WPN data acquisition, geocoding, collector credentials (if permitted), persistent storage, and verification workflows.

## Definition of done for first production milestone
- Store discovery source authorized and documented.
- Coverage tiled across full 300-mile circle; paging and deduplication tested.
- Store locations independently verified and geocoded.
- Coverage counts and collector health metrics available.
- Persistent DB storage configured (CI runners are ephemeral).
- No fabricated or demo rows in governed export.
