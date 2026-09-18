"""Shared fixtures — all XML is synthetic, no CNMV source bytes."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from cnmv_iic.artifacts.store import ArtifactStore

FONDCART_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FondCart>
  <FechaDatos>202512</FechaDatos>
  <Entidad>
    <Tipo>FI</Tipo>
    <NumeroRegistro>42</NumeroRegistro>
    <Compartimento>
      <NumeroCompartimento>0</NumeroCompartimento>
      <InversionesFinancieras>
        <ClaseIF>INTERIOR</ClaseIF>
        <DescripcionIF>Renta Variable Cotizada</DescripcionIF>
        <CodigoISIN>US0378331005</CodigoISIN>
        <DescripcionValor>ACCIONES|APPLE INC</DescripcionValor>
        <Divisa>USD</Divisa>
        <ValorMercado>1000.50</ValorMercado>
      </InversionesFinancieras>
      <InversionesFinancieras>
        <ClaseIF>EXTERIOR</ClaseIF>
        <DescripcionIF>Depositos</DescripcionIF>
        <DescripcionValor>DEPOSITO|BANCO X</DescripcionValor>
        <Divisa>EUR</Divisa>
        <ValorMercado>500.00</ValorMercado>
      </InversionesFinancieras>
      <InversionesFinancieras>
        <ClaseIF>EXTERIOR</ClaseIF>
        <DescripcionIF>IIC</DescripcionIF>
        <CodigoISIN>XXXXXXXXXXXX</CodigoISIN>
        <DescripcionValor>FONDO|MASKED</DescripcionValor>
        <Divisa>EUR</Divisa>
        <ValorMercado>499.50</ValorMercado>
      </InversionesFinancieras>
    </Compartimento>
  </Entidad>
</FondCart>
"""

PDV_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FondPatrimDisVar>
  <FechaDatos>202512</FechaDatos>
  <Entidad>
    <Tipo>FI</Tipo>
    <NumeroRegistro>42</NumeroRegistro>
    <CodigoDivisaIIC>EUR</CodigoDivisaIIC>
    <Compartimento>
      <NumeroCompartimento>0</NumeroCompartimento>
      <CarteraInterior>1000.50</CarteraInterior>
      <CarteraExterior>999.50</CarteraExterior>
      <InversionesDudosas>0.00</InversionesDudosas>
      <TotalPatrimonio>2000.00</TotalPatrimonio>
    </Compartimento>
  </Entidad>
</FondPatrimDisVar>
"""


FONDREGISTRO_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FondRegistro>
  <FechaDatos>202512</FechaDatos>
  <Entidad>
    <Tipo>FI</Tipo>
    <NumeroRegistro>9</NumeroRegistro>
    <Denominacion>FONMARCH, FI</Denominacion>
    <ETF>NO</ETF>
    <Gestora>
      <NumeroRegistroGestora>190</NumeroRegistroGestora>
      <DenominacionGestora>MARCH ASSET MANAGEMENT, S.G.I.I.C., S.A.U.</DenominacionGestora>
      <TipoGestora>SGIIC</TipoGestora>
      <GrupoGestora>
        <NumeroGrupoGestora>1</NumeroGrupoGestora>
        <DenominacionGrupoGestora>GRUPO MARCH</DenominacionGrupoGestora>
      </GrupoGestora>
    </Gestora>
    <Depositario>
      <NumeroRegistroDepositario>211</NumeroRegistroDepositario>
      <DenominacionDepositario>BANCO DEPOSITARIO, S.A.</DenominacionDepositario>
      <GrupoDepositario>
        <NumeroGrupoDepositario>7</NumeroGrupoDepositario>
        <DenominacionGrupoDepositario>GRUPO DEP</DenominacionGrupoDepositario>
      </GrupoDepositario>
    </Depositario>
    <Compartimento>
      <NumeroCompartimento>0</NumeroCompartimento>
      <DenominacionCompartimento>COMPARTIMENTO PRINCIPAL</DenominacionCompartimento>
      <Clase>
        <NumeroClase>1</NumeroClase>
        <ISIN>ES0138841038</ISIN>
        <DenominacionClase>CLASE A</DenominacionClase>
      </Clase>
      <Clase>
        <NumeroClase>2</NumeroClase>
        <ISIN>ES0138841004</ISIN>
        <DenominacionClase>CLASE C</DenominacionClase>
      </Clase>
    </Compartimento>
    <Compartimento>
      <NumeroCompartimento>1</NumeroCompartimento>
      <DenominacionCompartimento>COMPARTIMENTO UNO</DenominacionCompartimento>
      <Clase>
        <NumeroClase>1</NumeroClase>
        <ISIN>ES0138841012</ISIN>
        <DenominacionClase>CLASE S</DenominacionClase>
      </Clase>
    </Compartimento>
  </Entidad>
</FondRegistro>
"""


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def fondcart_zip() -> bytes:
    return make_zip({
        "FONDCART_202512.xml": FONDCART_XML,
        "FONDPATRIMDISVAR_202512.xml": PDV_XML,
        "FONDCART.xsd": b"<xsd/>",
        "FONDPATRIMDISVAR.xsd": b"<xsd/>",
    })


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture()
def artifact(store: ArtifactStore, fondcart_zip: bytes):
    art, _ = store.put(
        period="2025-12", source_page="t", source_url="t",
        content_type="application/zip", data=fondcart_zip,
    )
    return art
