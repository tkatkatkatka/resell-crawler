name: Classify Items (Gist-based Parallel)

on:
  workflow_dispatch:
    inputs:
      gist_id:
        description: 'GitHub Gist ID (청크 데이터 포함)'
        required: true
      gist_owner:
        description: 'Gist 소유자 계정명'
        required: true
      chunk_indices:
        description: '처리할 청크 인덱스 목록 (JSON 배열, 예: [0,1,2,34])'
        required: true

jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.gen.outputs.matrix }}
    steps:
      - id: gen
        run: |
          python3 - << 'PYEOF'
          import json, os
          indices = json.loads(os.environ['CHUNK_INDICES'])
          matrix  = json.dumps({"chunk": indices})
          with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
              f.write(f"matrix={matrix}\n")
          print(f"총 {len(indices)}개 청크 매트릭스 생성 완료")
          PYEOF
        env:
          CHUNK_INDICES: ${{ github.event.inputs.chunk_indices }}

  classify:
    needs: setup
    runs-on: ubuntu-latest
    timeout-minutes: 10
    strategy:
      matrix: ${{ fromJson(needs.setup.outputs.matrix) }}
      max-parallel: 20
      fail-fast: false

    steps:
      - name: Checkout central classifier
        run: |
          git clone https://github.com/dlfdlfdlfdlfdlf/resell-classifier.git classifier_repo
          echo "✅ resell-classifier 클론 완료"

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run classifier
        run: |
          cd classifier_repo
          python classifier.py \
            --gist_id    "${{ github.event.inputs.gist_id }}" \
            --gist_owner "${{ github.event.inputs.gist_owner }}" \
            --chunk_idx  "${{ matrix.chunk }}"

      - name: Upload result artifact
        uses: actions/upload-artifact@v4
        with:
          name: classify-result-${{ matrix.chunk }}
          path: classifier_repo/classify_result_${{ matrix.chunk }}.json
          retention-days: 1
        if: always()
