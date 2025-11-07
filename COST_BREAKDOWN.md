# loveUAD Cost Breakdown - Optimized for Budget

## Monthly Cost: ~$20-22

### Detailed Breakdown

| Service | Tier/Config | Monthly Cost | Notes |
|---------|-------------|--------------|-------|
| Cloud SQL PostgreSQL | db-f1-micro (0.6GB RAM) | $7 | Shared CPU, sufficient for pilot |
| Cloud SQL Storage | 10GB SSD | $2 | Grows as needed |
| Vertex AI Embeddings | text-embedding-004 | $1 | ~5000 queries/month |
| Gemini Flash API | 1.5 Flash | $8 | ~5000 responses/month |
| Cloud Run | 2M requests/month | $2 | Free tier covers most |
| Cloud Storage | Static files | $0.50 | Minimal usage |
| **TOTAL** | | **~$20-22** | |

## Performance Trade-offs

### db-f1-micro (Chosen)
- Cost: $7/month
- RAM: 0.6GB
- Query latency: 200-300ms
- Suitable for: Pilot with 20-30 users
- Max concurrent users: ~10-15

### Upgrade Path (If Needed)

| Tier | RAM | Query Latency | Cost/month | When to Use |
|------|-----|---------------|------------|-------------|
| db-f1-micro | 0.6GB | 200-300ms | $7 | Pilot phase |
| db-g1-small | 1.7GB | 100-150ms | $25 | 50-100 users |
| db-custom-1-3840 | 3.75GB | 50-100ms | $50 | 100-200 users |
| db-custom-2-7680 | 7.5GB | 50-100ms | $70 | 200+ users |

## Cost Optimization Tips

### During Development
1. Use Cloud SQL Proxy locally (free)
2. Stop Cloud SQL instance when not testing ($0 during off hours)
3. Use Vertex AI free tier (first 1000 requests/month free)

### During Pilot
1. Enable Cloud SQL automatic backups only weekly
2. Use response caching (reduces API calls by 20%)
3. Monitor and set budget alerts at $25/month
4. Batch embedding generation during ingestion

### If Budget Exceeds $25/month
1. Check for unnecessary API calls
2. Implement aggressive caching
3. Review Cloud Run memory settings
4. Consider Gemini Flash 8B (50% cheaper)

## Ingestion Cost (One-Time)

Loading 847MB of research papers:
- Vertex AI Embeddings: ~$4.25 (one-time)
- Processing time: 2-3 hours
- Cloud Run compute: ~$2 (one-time)
**Total one-time: ~$6.25**

## Cost Projections

### Pilot Phase (6 months)
- Monthly: $20-22
- Total: $120-132
- Plus one-time ingestion: $6
**6-month total: ~$126-138**

### After Funding
- Upgrade to db-g1-small: $25/month
- Better performance (100-150ms)
- Support 50-100 users

### At Scale (200+ users)
- Cloud SQL: $70/month (db-custom-2-7680)
- API costs: $40/month (20,000 queries)
- Cloud Run: $10/month
**Scale cost: ~$120/month**

## Budget Safety

Set up billing alerts:
```bash
# Alert at $15
gcloud alpha billing budgets create \
    --billing-account=YOUR_BILLING_ACCOUNT \
    --display-name="loveUAD Budget Alert" \
    --budget-amount=15USD

# Alert at $25
gcloud alpha billing budgets create \
    --billing-account=YOUR_BILLING_ACCOUNT \
    --display-name="loveUAD Hard Limit" \
    --budget-amount=25USD
```

## Why This is Sustainable

1. **Pilot Phase Budget**: £20-25/month fits pre-revenue stage
2. **Google Cloud Credits**: Requested $300-600 covers 15-30 months
3. **Grant Funding**: Innovate UK (if approved) covers scale-up costs
4. **Revenue Model**: £4.99/user/month = Break-even at 5 users

## Comparison to Original Estimate

| Item | Original | Optimized | Savings |
|------|----------|-----------|---------|
| Cloud SQL | $70 | $7 | $63 |
| Vertex AI | $2 | $1 | $1 |
| Gemini | $15 | $8 | $7 |
| Cloud Run | $5 | $2 | $3 |
| Storage | $1 | $0.50 | $0.50 |
| **TOTAL** | **$93** | **$20** | **$73/month** |

**Annual savings: $876**

## Bottom Line

Starting cost of **~$20/month** is:
- Affordable for pre-revenue startup
- Covered by Google Cloud credits request
- Sustainable through pilot phase
- Upgradable when funded

The f1-micro tier provides acceptable performance (200-300ms queries) for 20-30 pilot users. This can be upgraded seamlessly when funding is secured.
