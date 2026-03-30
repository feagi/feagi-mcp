# FEAGI MCP Roadmap

## Vision

Enable LLM-assisted neural circuit design by providing real-time observability and control of FEAGI systems. Make neurorobotics accessible to non-experts through AI guidance.

---

## Release Milestones

### v0.1.0 - Foundation (Current) ✓

**Goal:** Basic MCP server with core inspection tools

**Features:**
- [x] MCP server implementation with FastMCP
- [x] Genome upload/download/validate
- [x] Connectivity inspection
- [x] Signal path tracing
- [x] Cortical area listing
- [x] Embodiment status (with fallback)
- [x] Comprehensive documentation
- [x] Test suite
- [x] Cursor integration guide

**Status:** Released 2026-03-29

---

### v0.2.0 - Real Monitoring (Q2 2026)

**Goal:** Add actual neural activity monitoring

**Dependencies:**
- FEAGI REST API additions:
  - `GET /v1/monitor/cortical_activity`
  - `GET /v1/cortical_area/{id}/spikes`
  - `GET /v1/motor/output/snapshot`

**Features:**
- [ ] Real-time firing rate measurement
- [ ] Spike pattern analysis
- [ ] Motor output verification
- [ ] Sensory input inspection
- [ ] Activity heatmaps (visualization data)

**Success Criteria:**
- LLM can verify CPG is oscillating
- LLM can measure oscillation frequency
- LLM can confirm motor commands are generated

---

### v0.3.0 - Active Control (Q3 2026)

**Goal:** Enable direct neural stimulation and testing

**Dependencies:**
- FEAGI REST API additions:
  - `POST /v1/stimulate`
  - `POST /v1/stimulate/batch`
  - `WebSocket /ws/activity/stream`

**Features:**
- [ ] Direct cortical stimulation
- [ ] Batch stimulation for complex patterns
- [ ] Real-time activity streaming (WebSocket)
- [ ] Automated circuit testing framework
- [ ] Stimulation patterns library

**Success Criteria:**
- LLM can trigger walking by stimulating WalkStart
- LLM can test circuits without user intervention
- Continuous monitoring during testing

---

### v0.4.0 - Parameter Tuning (Q4 2026)

**Goal:** Interactive parameter adjustment and optimization

**Dependencies:**
- FEAGI runtime parameter update API
- Parameter effect prediction

**Features:**
- [ ] Temporary parameter updates (no genome reload)
- [ ] Parameter sweep automation
- [ ] Optimization suggestions based on observed behavior
- [ ] Parameter sensitivity analysis
- [ ] Rollback to previous parameter values

**Success Criteria:**
- LLM can tune CPG frequency without genome reload
- LLM can adjust synaptic weights iteratively
- Parameter changes visible within <100ms

---

### v0.5.0 - Advanced Analysis (2027 Q1)

**Goal:** Intelligent circuit analysis and recommendations

**Features:**
- [ ] Circuit pattern recognition (identify CPGs, FFNs, etc.)
- [ ] Performance profiling (firing rates, propagation delays)
- [ ] Anomaly detection (silent areas, runaway oscillations)
- [ ] Genome comparison and diff
- [ ] Optimization recommendations
- [ ] Circuit complexity metrics

**Success Criteria:**
- LLM can identify problematic circuits automatically
- LLM can suggest architectural improvements
- Comparative analysis between genome versions

---

### v0.6.0 - Templates & Libraries (2027 Q2)

**Goal:** Pre-built circuits and design patterns

**Features:**
- [ ] Circuit template repository
- [ ] Parametric circuit generation
- [ ] Best practices database
- [ ] Example genome library
- [ ] Interactive circuit builder
- [ ] Circuit composition tools

**Success Criteria:**
- LLM can instantiate CPG from template
- LLM can combine templates into complex behaviors
- Reduced time-to-first-working-circuit

---

### v1.0.0 - Production Ready (2027 Q3)

**Goal:** Enterprise-grade reliability and security

**Features:**
- [ ] Authentication (API keys, JWT)
- [ ] Authorization (role-based access control)
- [ ] Rate limiting
- [ ] Audit logging
- [ ] Multi-instance support
- [ ] TLS/HTTPS support
- [ ] Comprehensive metrics and monitoring
- [ ] Circuit marketplace integration
- [ ] Full test coverage (>90%)
- [ ] Production deployment guides

**Success Criteria:**
- Deployed in production FEAGI installations
- Used by 100+ users
- <0.1% tool call failure rate
- Security audit passed

---

## Feature Priorities

### Critical (Must Have)
1. Real neural activity monitoring
2. Direct stimulation
3. Parameter tuning without reload
4. WebSocket streaming

### High Priority (Should Have)
5. Circuit templates library
6. Performance profiling
7. Automated testing framework
8. Authentication and security

### Medium Priority (Nice to Have)
9. Genome diff and comparison
10. Pattern recognition
11. Optimization suggestions
12. Multi-instance support

### Low Priority (Future)
13. Circuit marketplace
14. Visual circuit builder
15. Machine learning integration
16. Cloud deployment

---

## Technical Debt

### Known Issues
1. `/v1/cortical_area/list` JSON parsing errors - needs FEAGI fix
2. No WebSocket support - waiting for FEAGI implementation
3. Limited test coverage - need integration tests
4. No authentication - security risk for production

### Refactoring Needs
1. Split `feagi_client.py` into smaller modules
2. Add caching layer for genome downloads
3. Implement retry logic with exponential backoff
4. Add request/response logging

---

## Community Requests

Track feature requests from users:

| Feature | Votes | Status | Target |
|---------|-------|--------|--------|
| Real-time monitoring | 🔥🔥🔥 | In progress | v0.2.0 |
| Circuit templates | 🔥🔥 | Planned | v0.6.0 |
| Direct stimulation | 🔥🔥 | Planned | v0.3.0 |
| Authentication | 🔥 | Planned | v1.0.0 |

---

## Dependencies Roadmap

### FEAGI Core Required Additions

**For v0.2.0:**
- REST endpoint: `GET /v1/monitor/cortical_activity?area={id}&duration={ms}`
  - Returns: `{firing_rate, active_neurons, spike_times}`
- REST endpoint: `GET /v1/motor/output?opu_id={id}`
  - Returns: `{device_values, last_update_time}`

**For v0.3.0:**
- REST endpoint: `POST /v1/stimulate`
  - Body: `{area_id, coordinates, potential, duration_ms}`
- WebSocket: `ws://host/v1/activity/stream?area={id}`
  - Streams: continuous firing events

**For v0.4.0:**
- REST endpoint: `PATCH /v1/cortical_area/{id}/parameters`
  - Body: `{parameter: value, temporary: true}`
  - Effect: Runtime update without genome reload

---

## Release Schedule

- **v0.1.0**: 2026-03-29 (Released)
- **v0.2.0**: 2026-06-30 (Target)
- **v0.3.0**: 2026-09-30 (Target)
- **v0.4.0**: 2026-12-31 (Target)
- **v0.5.0**: 2027-03-31 (Target)
- **v1.0.0**: 2027-09-30 (Target)

Schedule depends on FEAGI API development.

---

## How to Contribute

See roadmap items that interest you? Check [CONTRIBUTING.md](../CONTRIBUTING.md) and jump in!

High-impact areas:
1. Implement monitoring APIs in FEAGI Core
2. Add WebSocket support to FEAGI
3. Build circuit template library
4. Write integration tests
5. Create example genomes
