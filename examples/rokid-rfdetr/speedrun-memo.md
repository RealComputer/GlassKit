### Class list (composite, 7 classes)

#### Nigiri

1. `nigiri_rice_in_hand`

* Visual definition: a hand holding a formed rice ball for nigiri, before tuna is applied.

2. `nigiri_on_plate`

* Visual definition: completed tuna nigiri placed on a plate.

#### Maki

3. `maki_nori_on_makisu`

* Visual definition: makisu placed with a nori sheet laid on top (ready to add ingredients).

4. `maki_ready_with_rice_cucumber`

* Visual definition: nori on makisu with rice placed and cucumber placed (flat, ready to roll).

5. `maki_piece_on_plate`

* Visual definition: a single cut cucumber maki piece on a plate.

#### Gunkan

6. `gunkan_rice_nori_base_ready`

* Visual definition: gunkan base completed (rice formed, nori wrapped as a ring/cup), no ikura on top yet.

7. `gunkan_ikura_on_plate`

* Visual definition: finished ikura gunkan placed on a plate.

---

```json
[
  {
    "name": "Tuna Nigiri",
    "splits": [
      { "label": "Pick up rice", "complete_on_class": "nigiri_rice_in_hand" },
      { "label": "Top with tuna", "complete_on_class": "nigiri_on_plate" }
    ]
  },
  {
    "name": "Cucumber Maki",
    "splits": [
      { "label": "Lay nori", "complete_on_class": "maki_nori_on_makisu" },
      { "label": "Add rice and cucumber", "complete_on_class": "maki_ready_with_rice_cucumber" },
      { "label": "Roll and cut", "complete_on_class": "maki_piece_on_plate" }
    ]
  },
  {
    "name": "Ikura Gunkan",
    "splits": [
      { "label": "Form rice, wrap nori", "complete_on_class": "gunkan_rice_nori_base_ready" },
      { "label": "Top with ikura", "complete_on_class": "gunkan_ikura_on_plate" }
    ]
  }
]
```
