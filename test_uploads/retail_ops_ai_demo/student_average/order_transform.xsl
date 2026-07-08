<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>

  <!-- Average attempt: uses medium segment threshold -->
  <xsl:template match="/orders">
    <orders_report>
      <xsl:apply-templates select="order"/>
    </orders_report>
  </xsl:template>

  <xsl:template match="order">
    <order>
      <id><xsl:value-of select="@id"/></id>
      <region><xsl:value-of select="region"/></region>
      <segment>
        <xsl:choose>
          <xsl:when test="number(value) &gt;= 1400">high</xsl:when>
          <xsl:otherwise>standard</xsl:otherwise>
        </xsl:choose>
      </segment>
      <status><xsl:value-of select="status"/></status>
    </order>
  </xsl:template>
</xsl:stylesheet>
